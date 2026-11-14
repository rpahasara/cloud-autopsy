"""Synthetic incident workload (CA-P2-004g / CA-P2-007a), test-only. Runs in the disposable kind cluster.

It simulates a checkout service with a database pool whose size is ``DB_POOL_MAX``. Every line it writes
to stdout carries the sequence envelope (plan section 4.2)::

  CA1 boot=<8 hex> seq=<n> [synced=<n-1> lag_ms=<n>] <TEMPLATE> [key=value ...]

**Write-after-append handshake (plan section 4.9).** After writing line ``i``, the workload waits until
line ``i`` appears in its own node log file (read through a read-only ``hostPath`` of
``/var/log/pods/<namespace>_<pod>_<uid>/<container>/``) before it writes line ``i+1``, which then carries
``synced=i``. If line ``i`` does not appear within ``HANDSHAKE_TIMEOUT_S``, the next line carries no
``synced`` (the product then has no handshake bound from that point; it never assumes one).

Demand: ``DEMAND`` is ``steady:<n>`` or ``ramp:<base>:<peak>:<after_s>[:<until_s>]`` (``peak`` from ``after_s``
until ``until_s`` seconds after start, otherwise ``base``). While demand exceeds the pool, the workload logs ``POOL_EXHAUSTED``.
``PLANTED=1`` adds enveloped lines with planted sensitive text under a template the catalog does not know:
they count for continuity but must never be stored.

Standard library only. Values are synthetic.
"""

import glob
import os
import secrets
import signal
import sys
import time

POD_UID, POD_NAME, NAMESPACE = os.environ["POD_UID"], os.environ["POD_NAME"], os.environ["POD_NAMESPACE"]
CONTAINER = os.environ.get("CONTAINER_NAME", "checkout-api")
POOL = int(os.environ["DB_POOL_MAX"])
DEMAND = os.environ.get("DEMAND", "steady:2")
INTERVAL_S = float(os.environ.get("INTERVAL_S", "1"))
PLANTED = os.environ.get("PLANTED") == "1"
HANDSHAKE_TIMEOUT_S = float(os.environ.get("HANDSHAKE_TIMEOUT_S", "5"))
LOG_DIR = f"/var/log/pods/{NAMESPACE}_{POD_NAME}_{POD_UID}/{CONTAINER}"
PLANTED_TEXT = ("password=PLANTED-LOG-PASSWORD-1d2", "authorization=Bearer_PLANTED-LOG-TOKEN-8e1",
                "user=PLANTED-LOG-EMAIL@example.com", "jwt=eyJhbGciOiJIUzI1NiJ9.PLANTED-LOG-JWT.sig")

BOOT = secrets.token_hex(4)
START = time.monotonic()
state = {"seq": 0, "synced": False, "lag_ms": 0, "file": None, "offset": 0, "stop": False}


def _current_log_file():
    files = sorted(glob.glob(f"{LOG_DIR}/*.log"), key=lambda p: int(os.path.basename(p).split(".")[0]))
    return files[-1] if files else None


def _appended(needle, deadline):
    """True once ``needle`` appears in a complete line of the node log file. Reads forward only."""
    while time.monotonic() < deadline:
        path = _current_log_file()
        if path != state["file"]:
            state["file"], state["offset"] = path, 0
        if path:
            try:
                with open(path, "rb") as f:
                    f.seek(state["offset"])
                    data = f.read()
            except OSError:
                data = b""
            cut = data.rfind(b"\n") + 1
            state["offset"] += cut
            if needle in data[:cut]:
                return True
        time.sleep(0.005)
    return False


def emit(body):
    state["seq"] += 1
    seq = state["seq"]
    handshake = f" synced={seq - 1} lag_ms={state['lag_ms']}" if state["synced"] and seq > 1 else ""
    sys.stdout.write(f"CA1 boot={BOOT} seq={seq}{handshake} {body}\n")
    sys.stdout.flush()
    written = time.monotonic()
    state["synced"] = _appended(f"CA1 boot={BOOT} seq={seq} ".encode(), written + HANDSHAKE_TIMEOUT_S)
    state["lag_ms"] = int((time.monotonic() - written) * 1000)


def demand(elapsed):
    kind, *values = DEMAND.split(":")
    if kind == "steady":
        return int(values[0])
    base, peak, after = int(values[0]), int(values[1]), float(values[2])
    until = float(values[3]) if len(values) > 3 else float("inf")
    return peak if after <= elapsed < until else base


def _stop(signum, frame):  # noqa: ARG001
    state["stop"] = True


def main():
    signal.signal(signal.SIGTERM, _stop)
    emit(f"STARTED pod_uid={POD_UID} container={CONTAINER}")
    emit(f"CONFIG_LOADED key=pool.maxConnections value={POOL}")
    n = 0
    while not state["stop"]:
        time.sleep(INTERVAL_S)
        if state["stop"]:
            break
        n += 1
        if PLANTED and n % 4 == 0:
            emit("DEBUG_DUMP " + PLANTED_TEXT[(n // 4) % len(PLANTED_TEXT)])
        in_use = demand(time.monotonic() - START)
        if in_use > POOL:
            emit(f"POOL_EXHAUSTED pool=checkout-db in_use={in_use} max={POOL}")
        elif n % 5 == 0:
            emit("REQUEST_OK")
        else:
            emit("HEARTBEAT")
    emit("STOPPED")


if __name__ == "__main__":
    main()
