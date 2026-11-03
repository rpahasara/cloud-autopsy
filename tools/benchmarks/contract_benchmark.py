"""Non-gating timing benchmark for the provisional contract parsers (CA-P2-002).

Not part of the unit suite or CI. It reports timings with the machine environment so they
can be compared over time; it never fails on a slow run. Correctness of the same inputs is
asserted deterministically in tests/contracts/test_canonical_limits.py.

Usage: python -I tools/benchmarks/contract_benchmark.py [--repeat N]
"""

import argparse
import json
import os
import platform
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from cloud_autopsy.contracts import canonical  # noqa: E402

BACKSLASH = chr(92).encode()


def cases():
    return {
        "deep-nesting-1M": b"[" * 1_000_000,
        "long-integer-1M": b"9" * 1_000_000,
        "escaped-string-1M": b'"' + BACKSLASH * 2 * 500_000 + b'"',
        "unterminated-string-1M": b'"' + BACKSLASH * 1_000_000,
        "node-ceiling-800K": b"[" + b"0," * 400_000 + b"0]",
    }


def measure(doc, repeat):
    timings = []
    for _ in range(repeat):
        start = time.perf_counter()
        try:
            canonical.loads(doc)
            outcome = "accepted"
        except canonical.CanonicalError as exc:
            outcome = exc.code
        timings.append(time.perf_counter() - start)
    return outcome, timings


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repeat", type=int, default=5)
    args = parser.parse_args(argv)
    report = {
        "benchmark": "ca-contract-parsers/0.1",
        "gating": False,
        "environment": {"python": platform.python_version(), "implementation": platform.python_implementation(),
                        "system": platform.system(), "machine": platform.machine(), "cpus": os.cpu_count()},
        "results": [],
    }
    for name, doc in cases().items():
        outcome, timings = measure(doc, args.repeat)
        report["results"].append({"case": name, "bytes": len(doc), "outcome": outcome,
                                  "min_s": round(min(timings), 4), "max_s": round(max(timings), 4)})
    print(json.dumps(report, indent=2))
    return 0  # never gating


if __name__ == "__main__":
    sys.exit(main())
