"""Write the six synthetic scenario-001 variants as evidence bundles (CA-P2-004a).

  python -I tools/export_bundles.py [--out examples/bundles]

Each bundle holds only contract records (registry, plan, declared clocks, batches): no expected
outcome, ground truth, secret or credential. The output directory must not already contain them.
"""

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from cloud_autopsy.app import bundle  # noqa: E402
from cloud_autopsy.synthetic import scenario_001 as scenario  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=REPO / "examples" / "bundles")
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    for variant in scenario.VARIANTS:
        path = bundle.export_variant(args.out / variant, variant)
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
