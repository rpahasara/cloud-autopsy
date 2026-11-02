"""Shared test setup: put ``src`` on the path and load the vector file with the stdlib parser."""

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "src"
PACKAGE = SRC / "cloud_autopsy"
VECTORS = PACKAGE / "contracts" / "vectors" / "ca-jcs-profile-0.1-provisional.json"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def load_vectors():
    return json.loads(VECTORS.read_bytes().decode("utf-8"))


def vector_input(vector):
    if "input_hex" in vector:
        return bytes.fromhex(vector["input_hex"])
    return vector["input"].encode("utf-8", "surrogatepass")
