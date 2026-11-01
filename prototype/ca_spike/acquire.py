"""Offline fixture "connector": typed acquisition outcomes with explicit bounds.

No network access. A failed or denied acquisition is never reported as empty, and
oversized observations are rejected and counted rather than silently dropped.
"""

import random

from .model import ACQUISITION_STATUSES, AcquisitionOutcome


def _too_long(value, limit):
    if isinstance(value, str):
        return len(value) > limit
    if isinstance(value, dict):
        return any(_too_long(k, limit) or _too_long(v, limit) for k, v in value.items())
    if isinstance(value, list):
        return any(_too_long(v, limit) for v in value)
    return False


def acquire(observations_doc, plan, permute_seed=None, duplicate_delivery=False):
    """Return (outcomes, deliveries); deliveries are (query_id, source_id, observation) tuples.

    ``permute_seed`` and ``duplicate_delivery`` simulate delivery-order permutation and
    at-least-once retries so tests can show the assembled bundle is unaffected.
    """
    limits = plan["limits"]
    outcomes, deliveries = [], []
    total = 0
    for acq in observations_doc["acquisitions"]:
        status = acq.get("status", "complete")
        if status not in ACQUISITION_STATUSES:
            raise ValueError(f"unknown acquisition status {status!r}")
        received = rejected = 0
        if status in ("failed", "denied"):
            accepted = []
        else:
            accepted = []
            for obs in acq["observations"]:
                received += 1
                if total >= limits["max_observations"] or _too_long(obs, limits["max_string_chars"]):
                    rejected += 1
                    continue
                total += 1
                accepted.append(obs)
            if rejected:
                status = "truncated"
            elif not accepted and status == "complete":
                status = "empty"
        outcomes.append(AcquisitionOutcome(
            query_id=acq["query_id"], source_id=acq["source_id"], status=status,
            reason=acq.get("reason") if status in ("failed", "denied") else (
                "bound_exceeded" if status == "truncated" else None),
            window=acq["window"], observations_received=received, observations_rejected=rejected))
        deliveries.extend((acq["query_id"], acq["source_id"], obs) for obs in accepted)

    if duplicate_delivery:
        deliveries = deliveries + deliveries[::3]
    if permute_seed is not None:
        rng = random.Random(permute_seed)
        rng.shuffle(deliveries)
        rng.shuffle(outcomes)
    return outcomes, deliveries
