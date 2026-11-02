"""Seeded property checks: idempotence, insertion-order independence and a stdlib differential."""

import json
import random
import unittest

import _support  # noqa: F401
from cloud_autopsy.contracts import canonical

ALPHABET = ["a", "B", "0", " ", "\"", "\\", "/", "\u0000", "\u001f", "\u007f", "é", "é",
            " ", "€", "דּ", "｡", "", "\U0001F600", "\U00010000"]


def random_value(rng, depth=0, bmp_only=False):
    alphabet = [c for c in ALPHABET if not bmp_only or ord(c[-1]) <= 0xFFFF]
    text = lambda: "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 4)))  # noqa: E731
    kind = rng.randint(0, 6 if depth < 5 else 3)
    if kind == 0:
        return rng.choice([None, True, False])
    if kind == 1:
        return rng.randint(-canonical.MAX_SAFE_INTEGER, canonical.MAX_SAFE_INTEGER)
    if kind in (2, 3):
        return text()
    if kind == 4:
        return [random_value(rng, depth + 1, bmp_only) for _ in range(rng.randint(0, 4))]
    return {text(): random_value(rng, depth + 1, bmp_only) for _ in range(rng.randint(0, 4))}


def shuffled(value, rng):
    if isinstance(value, dict):
        items = list(value.items())
        rng.shuffle(items)
        return {k: shuffled(v, rng) for k, v in items}
    if isinstance(value, list):
        return [shuffled(v, rng) for v in value]
    return value


class PropertyTests(unittest.TestCase):
    SEEDS = range(300)

    def test_idempotent_and_insertion_order_independent(self):
        for seed in self.SEEDS:
            rng = random.Random(seed)
            value = random_value(rng)
            encoded = canonical.canonical_bytes(value)
            with self.subTest(seed=seed):
                self.assertEqual(canonical.canonicalize(encoded), encoded)
                self.assertEqual(canonical.canonical_bytes(shuffled(value, rng)), encoded)
                self.assertEqual(canonical.loads(encoded), value)

    def test_matches_stdlib_serializer_when_orders_agree(self):
        # For BMP-only keys UTF-16 order equals code-point order, so json.dumps(sort_keys=True)
        # is an independent reference for escaping and layout.
        for seed in self.SEEDS:
            value = random_value(random.Random(seed), bmp_only=True)
            reference = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            with self.subTest(seed=seed):
                self.assertEqual(canonical.canonical_bytes(value), reference.encode("utf-8"))


if __name__ == "__main__":
    unittest.main()
