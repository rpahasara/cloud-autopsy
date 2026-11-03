"""Paged frozen-input manifests: capacity, bounds and full verification (PR #19 review, CA-P2-002d)."""

import copy
import random
import unittest

import _evidence_support as ES
import _manifest_support as M
from cloud_autopsy.contracts import canonical, errors, frozen_input as fi, plan as pl
from cloud_autopsy.contracts.errors import ContractError

MEMBERS = 10_000
PER_BATCH = 1_000


def code_of(fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except ContractError as exc:
        return exc.code
    return None


def large_plan():
    record = M.plan_record(["metrics"])
    record["limits"] = {**record["limits"], "max_batches_per_acquisition": 20, "max_batch_deliveries": 40,
                        "max_observations_per_batch": PER_BATCH, "max_observations_total": MEMBERS,
                        "max_total_bytes": 50_000_000}
    return pl.RunPlan.from_record(record, M.REGISTRY)


def metric_batches(plan, members=MEMBERS, per_batch=PER_BATCH):
    """Chained complete batches covering the window with ``members`` distinct metric samples."""
    _, template = ES.case("metric")
    count = members // per_batch
    step = (plan.window_end_ms - plan.window_start_ms) // count
    batches = []
    for b in range(count):
        observations = []
        for i in range(per_batch):
            n = b * per_batch + i
            obs = copy.deepcopy(template)
            obs["source_version"] = f"sample-{n:06d}"
            obs["source_ref"] = f"prom:checkout_api:error_ratio@{n:06d}"
            observations.append(obs)
        start = plan.window_start_ms + b * step
        end = plan.window_end_ms if b == count - 1 else start + step
        batches.append({
            "contract_version": "ca-acquisition-batch/0.1-provisional", "plan_digest": plan.digest,
            "source_id": "prometheus", "query_id": "prom.checkout-api", "batch_key": f"m-{b}", "sequence": b + 1,
            "outcome": "complete", "reason": None,
            "coverage": {"start": _rfc3339(start), "end": _rfc3339(end)},
            "cursor": {"before": None if b == 0 else f"c{b}", "after": f"c{b + 1}"},
            "truncation": {"truncated": False, "reason": None, "omitted_count": None},
            "observations": observations, "delivery": {"attempt": 1}})
    return batches


def _rfc3339(epoch_ms):
    seconds, ms = divmod(epoch_ms, 1000)
    import datetime
    stamp = datetime.datetime.fromtimestamp(seconds, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    return f"{stamp}.{ms:03d}Z"


def reforge(root, pages):
    """What an attacker able to recompute every digest would produce from modified pages."""
    root = copy.deepcopy(root)
    by_collection = {}
    for page in pages:
        by_collection.setdefault(page["collection"], []).append(page)
    for name in fi.COLLECTION_KEYS:
        commitments = []
        for page in by_collection.get(name, []):
            blob = canonical.canonical_bytes(page)
            commitments.append({"index": page["page_index"], "item_count": len(page["items"]),
                                "digest": fi.page_digest(blob)})
        root["collections"][name]["pages"] = commitments
    body = {k: v for k, v in root.items() if k != "manifest_digest"}
    root["manifest_digest"] = fi.manifest_digest(body)
    return root


class LargeManifestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan = large_plan()
        cls.batches = metric_batches(cls.plan)
        cls.sealed = fi.seal(cls.plan, M.REGISTRY, cls.batches)
        cls.root, cls.pages = cls.sealed.root(), cls.sealed.pages()

    def evidence_pages(self):
        return [p for p in self.pages if p["collection"] == "evidence"]

    def test_ten_thousand_memberships_are_paged_within_bounds(self):
        self.assertEqual(self.root["status"], fi.COMPLETE)
        evidence = self.root["collections"]["evidence"]
        self.assertEqual(evidence["item_count"], MEMBERS)
        self.assertGreaterEqual(len(evidence["pages"]), MEMBERS // fi.PAGE_MAX_ITEMS)
        self.assertEqual(self.root["collections"]["evidence_provenance"]["item_count"], MEMBERS)
        self.assertLess(len(self.sealed.root_bytes), 64 * 1024)
        for blob in self.sealed.page_bytes:
            self.assertLessEqual(len(blob), fi.PAGE_MAX_BYTES)
        for page in self.pages:
            self.assertLessEqual(len(page["items"]), fi.PAGE_MAX_ITEMS)
        members = fi.collection_items(self.sealed, "evidence")
        self.assertEqual(len({m["evidence_id"] for m in members}), MEMBERS)
        self.assertTrue(all(m["coverage"] == fi.VERIFIED for m in members))

    def test_full_verification_and_replay(self):
        fi.verify_full(self.root, self.pages, self.plan, M.REGISTRY, self.sealed.digest)
        fi.verify_full(self.root, self.pages + self.pages[:3], self.plan, M.REGISTRY)  # duplicates tolerated
        resealed = fi.verify_replay(self.root, list(reversed(self.pages)), self.plan, M.REGISTRY,
                                    list(reversed(self.batches)), self.sealed.digest)
        self.assertEqual(resealed.page_bytes, self.sealed.page_bytes)

    def test_root_only_verification_does_not_prove_pages(self):
        self.assertEqual(fi.verify_root(self.root, self.plan, M.REGISTRY), self.root)
        self.assertEqual(code_of(fi.verify_full, self.root, [], self.plan, M.REGISTRY), errors.PAGE_MISSING)

    def test_incomplete_page_sets_never_pass(self):
        evidence = self.evidence_pages()
        others = [p for p in self.pages if p["collection"] != "evidence"]
        for drop in (0, len(evidence) // 2, len(evidence) - 1):
            with self.subTest(drop=drop):
                partial = others + evidence[:drop] + evidence[drop + 1:]
                self.assertEqual(code_of(fi.verify_full, self.root, partial, self.plan, M.REGISTRY),
                                 errors.PAGE_MISSING)
                # Even a fully recomputed root over the reduced set fails: counts or the sealed digest.
                forged = reforge(self.root, partial)
                self.assertEqual(code_of(fi.verify_full, forged, partial, self.plan, M.REGISTRY),
                                 errors.PAGE_INVALID)
                forged["collections"]["evidence"]["item_count"] -= len(evidence[drop]["items"])
                forged = reforge(forged, partial)
                self.assertEqual(code_of(fi.verify_full, forged, partial, self.plan, M.REGISTRY,
                                         self.sealed.digest), errors.MANIFEST_DIGEST_MISMATCH)

    def test_tampered_pages(self):
        evidence = self.evidence_pages()
        tampered = copy.deepcopy(evidence[1])
        tampered["items"][5]["coverage"] = fi.UNVERIFIED
        pages = [p for p in self.pages if p is not evidence[1]] + [tampered]
        self.assertEqual(code_of(fi.verify_full, self.root, pages, self.plan, M.REGISTRY),
                         errors.PAGE_DIGEST_MISMATCH)
        stranger = copy.deepcopy(evidence[0])
        stranger["page_index"] = 999
        self.assertEqual(code_of(fi.verify_full, self.root, self.pages + [stranger], self.plan, M.REGISTRY),
                         errors.PAGE_UNEXPECTED)

    def test_structural_forgeries_with_recomputed_digests(self):
        evidence = self.evidence_pages()
        others = [p for p in self.pages if p["collection"] != "evidence"]

        def forged(mutate):
            pages = copy.deepcopy(evidence)
            mutate(pages)
            all_pages = others + pages
            return code_of(fi.verify_full, reforge(self.root, all_pages), all_pages, self.plan, M.REGISTRY)

        def duplicate_across_pages(pages):
            pages[0]["items"].append(pages[1]["items"][0])

        def unsorted_within_page(pages):
            pages[2]["items"][0], pages[2]["items"][1] = pages[2]["items"][1], pages[2]["items"][0]

        def duplicate_within_page(pages):
            pages[3]["items"][1] = pages[3]["items"][0]

        def extra_field(pages):
            pages[4]["items"][0]["note"] = "x"

        def swapped_order(pages):
            pages[0], pages[1] = pages[1], pages[0]
            pages[0]["page_index"], pages[1]["page_index"] = 0, 1

        def overfull(pages):
            pages[0]["items"] += pages[1]["items"][:fi.PAGE_MAX_ITEMS]
            del pages[1]
            for i, page in enumerate(pages):
                page["page_index"] = i

        for mutate in (duplicate_across_pages, unsorted_within_page, duplicate_within_page, extra_field,
                       swapped_order, overfull):
            with self.subTest(mutate.__name__):
                self.assertEqual(forged(mutate), errors.PAGE_INVALID)

    def test_malformed_commitments_are_typed(self):
        root = copy.deepcopy(self.root)
        root["collections"]["evidence"]["pages"][0]["item_count"] = fi.PAGE_MAX_ITEMS + 1
        body = {k: v for k, v in root.items() if k != "manifest_digest"}
        root["manifest_digest"] = fi.manifest_digest(body)
        self.assertEqual(code_of(fi.verify_root, root, self.plan, M.REGISTRY), errors.PAGE_INVALID)
        root["collections"]["unknown"] = {"item_count": 0, "pages": []}
        root["manifest_digest"] = fi.manifest_digest({k: v for k, v in root.items() if k != "manifest_digest"})
        self.assertEqual(code_of(fi.verify_root, root, self.plan, M.REGISTRY), errors.PAGE_INVALID)

    def test_large_manifest_is_order_independent(self):
        shuffled = list(self.batches)
        random.Random(5).shuffle(shuffled)
        resealed = fi.seal(self.plan, M.REGISTRY, shuffled + shuffled[:2])
        self.assertEqual((resealed.root_bytes, resealed.page_bytes), (self.sealed.root_bytes, self.sealed.page_bytes))


class UpperBoundTests(unittest.TestCase):
    """Capacity at the provisional ceilings, exercised on the paging layer directly."""

    def test_one_hundred_thousand_members_page_within_bounds(self):
        items = [{"evidence_id": f"{fi.MANIFEST_ALGORITHM}:{i:064x}", "content_digest": f"c:{i:064x}",
                  "coverage": fi.VERIFIED, "batch_count": 1} for i in range(pl.LIMIT_CEILINGS["max_observations_total"])]
        commitment, blobs = fi._paginate("evidence", items)
        self.assertEqual(commitment["item_count"], len(items))
        self.assertLessEqual(len(blobs), 2 * len(items) // fi.PAGE_MAX_ITEMS + 1)
        self.assertTrue(all(len(b) <= fi.PAGE_MAX_BYTES for b in blobs))
        self.assertEqual(sum(p["item_count"] for p in commitment["pages"]), len(items))

    def test_worst_case_root_fits_the_canonical_ceiling(self):
        # Upper bound on pages under the ceilings: evidence and provenance <= 100k items each; batches and
        # coverage <= 64 acquisitions x 1,000 batches; gaps <= one per batch, per hole, per conflict and per
        # conflicted identity. Byte bounds can add pages, so allow three times the item-count page estimate.
        ceilings, acquisitions = pl.LIMIT_CEILINGS, pl.MAX_EXPECTED_ACQUISITIONS
        batches = acquisitions * ceilings["max_batches_per_acquisition"]
        estimate = {"evidence": ceilings["max_observations_total"],
                    "evidence_provenance": ceilings["max_observations_total"],
                    "batches": batches, "coverage": batches,
                    "gaps": 3 * batches + ceilings["max_observations_total"]}
        collections = {name: {"item_count": count, "pages": [
            {"index": i, "item_count": fi.PAGE_MAX_ITEMS, "digest": fi.PAGE_ALGORITHM + ":" + "0" * 64}
            for i in range(3 * count // fi.PAGE_MAX_ITEMS + 1)]} for name, count in estimate.items()}
        summaries = [{"source_id": "s" * 64, "query_id": "q" * 64, "mandatory": True, "status": "partial",
                      "batch_count": 1000, "conflicting_batch_keys": 1000, "observations_received": 100000,
                      "verified_ms": 3600000, "gap_count": 3000}] * acquisitions
        size = len(canonical.canonical_bytes({"collections": collections, "acquisitions": summaries,
                                              "padding": "x" * 8192}))
        self.assertLess(size, canonical.CEILING_BYTES)

    def test_largest_items_fit_one_page(self):
        conflict_gap = fi._gap("batch", fi.UNVERIFIABLE, ["batch_conflict"], source_id="s" * 64, query_id="q" * 64,
                               mandatory=True, batch_digests=[f"{canonical.DIGEST_ALGORITHM}:{i:064x}"
                                                              for i in range(pl.LIMIT_CEILINGS[
                                                                  "max_batches_per_acquisition"])])
        commitment, blobs = fi._paginate("gaps", [conflict_gap])
        self.assertEqual(len(blobs), 1)
        self.assertLessEqual(len(blobs[0]), fi.PAGE_MAX_BYTES)


if __name__ == "__main__":
    unittest.main()
