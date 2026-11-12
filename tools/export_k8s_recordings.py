"""Write the synthetic recorded Kubernetes examples to examples/k8s-recordings/ (CA-P2-004c).

  python -I tools/export_k8s_recordings.py [--out DIR]

The target directory must not exist. A test requires the committed examples to equal a fresh export.
"""

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from cloud_autopsy.app import k8s_recording as K  # noqa: E402
from cloud_autopsy.synthetic import k8s_recordings as R  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=REPO / "examples" / "k8s-recordings")
    args = parser.parse_args(argv)
    args.out.mkdir(parents=False, exist_ok=False)
    for name in R.RECORDINGS + R.RECORDINGS_V2:
        K.export_example(args.out / name, name)
        print(f"wrote {args.out / name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
