"""Stress real-browser startup through the test harness (test-only; loopback only).

  python -I tests/browser/startup_stress.py [--sequential N] [--concurrency C] [--rounds R]

Launches the browser N times one after another, then R rounds of C at once; each launch evaluates
one expression and is closed. Prints the first (cold) launch's time, the spread, any retried or
failed launches, and fails if any launch failed or left a profile directory behind.
"""

import argparse
import glob
import os
import statistics
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _cdp  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sequential", type=int, default=20)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--rounds", type=int, default=3)
    args = parser.parse_args()
    if not _cdp.find_browser():
        print("FAIL: no Chromium-family browser found (set CA_BROWSER)")
        return 1
    times, retried, failures = [], [], []
    lock = threading.Lock()

    def one(index):
        began = time.monotonic()
        try:
            b = _cdp.Browser(1024, 700)
            try:
                if b.js("1 + 1") != 2:
                    raise RuntimeError("evaluation returned the wrong value")
            finally:
                problems = b.close()
            with lock:
                times.append((index, time.monotonic() - began))
                if b.start_attempts > 1:
                    retried.append(index)
                if problems:
                    failures.append(f"launch {index} cleanup: {problems}")
        except Exception as error:  # noqa: BLE001 - every failure is reported, none is retried here
            with lock:
                failures.append(f"launch {index}: {type(error).__name__}: {error}")

    pattern = os.path.join(tempfile.gettempdir(), "ca-browser-*")
    before = set(glob.glob(pattern))
    index = 0
    for _ in range(args.sequential):
        one(index)
        index += 1
    for _ in range(args.rounds):
        threads = []
        for _ in range(args.concurrency):
            threads.append(threading.Thread(target=one, args=(index,)))
            index += 1
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    left = set(glob.glob(pattern)) - before
    durations = [d for _, d in times]
    print(f"launches={index} ok={len(times)} failed={len(failures)} retried={len(retried)} profiles_left={len(left)}")
    if durations:
        first = dict(times).get(0)
        print(f"first (cold) launch: {first:.2f}s" if first is not None else "first (cold) launch: failed")
        print(f"startup+evaluate seconds: median={statistics.median(durations):.2f} max={max(durations):.2f}")
    for line in failures:
        print("FAILURE:", line)
    for path in sorted(left):  # what reappeared, to tell a late writer from a failed removal
        entries = sorted(os.listdir(path))[:10] if os.path.isdir(path) else []
        print(f"LEFT: {os.path.basename(path)} entries={entries}")
    return 1 if failures or left else 0


if __name__ == "__main__":
    sys.exit(main())
