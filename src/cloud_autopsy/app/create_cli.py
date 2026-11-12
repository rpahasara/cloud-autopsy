"""Create investigations from evidence bundles (CA-P2-004a). Synthetic data only.

  python -I tools/create_investigation.py --offline BUNDLE [BUNDLE ...]
      Validate each bundle and run the engine in memory. No database, no network. Results are
      labelled "offline: engine-checked, not database-verified".

  python -I tools/create_investigation.py BUNDLE [BUNDLE ...] [--serve [--port N]] [--grant-dir DIR]
      Start a disposable, loopback-only PostgreSQL (Docker), create each investigation through the
      least-privileged roles, and verify each stored result on read. With --serve, also issue a
      bearer token for exactly those runs into a new private directory outside Git, and serve the
      existing read-only API and dashboard on 127.0.0.1 until Ctrl+C; then everything is removed.
      The token is never printed, only the path of its file.

Exit status: 0 when every bundle succeeded; 1 when any bundle was refused or failed; 2 for usage errors.
"""

import argparse
import json
import shutil
import sys
from pathlib import Path

from . import bundle as B
from . import create as C


def _offline(paths, out):
    ok, rows = True, []
    for path in paths:
        try:
            inv = C.investigate_offline(B.load(path))
        except B.BundleError as exc:
            ok = False
            rows.append({"bundle": str(path), "status": "refused", "code": exc.code})
            continue
        rows.append({"bundle": inv.bundle_id, "status": "ok", "verified": False, "label": inv.label,
                     "outcome": inv.result["outcome"]["status"], "mechanism": inv.result["outcome"]["mechanism"],
                     "result_digest": inv.result_digest})
        if out:
            out.mkdir(parents=True, exist_ok=True)
            (out / f"{inv.bundle_id}.offline.result.json").write_bytes(inv.result_bytes)
    return ok, rows


def _print(rows):
    for r in rows:
        if r["status"] == "ok":
            run = f" run {r['run_id']}" if r.get("run_id") else ""
            print(f"{r['bundle']:44} {r['outcome']:9} {str(r['mechanism']):23} {r['result_digest'].split(':')[-1][:16]}"
                  f"  [{r['label']}]{run}")
        else:
            life = r.get("lifecycle")
            print(f"{r['bundle']:44} {r['status'].upper()}: {r.get('code') or r.get('reason')}"
                  + (f" at {r['stage']}" if r.get("stage") else "") + (f" (run {r['run_id']})" if r.get("run_id") else "")
                  + (f" [run state: {life['state']}" + (f", {life['failure_reason']}" if life.get("failure_reason") else "")
                     + "; not verified]" if life else ""))


def run_status(database, run_id):
    """The run's lifecycle state for the CLI, read like the API reads it (``ca.run_status`` as
    ``ca_engine``); None when it cannot be read. Lifecycle metadata only, never a verified result."""
    try:
        from ..db import status
        db = database.connect("ca_engine")
    except Exception:  # noqa: BLE001 -- the failure row is still reported, without a state
        return None
    try:
        found = status.load_status(db, run_id)
        return found.to_record() if found else None
    except Exception:  # noqa: BLE001
        return None
    finally:
        db.close()


def create_all(database, paths):
    """Create each bundle in ``database`` (a ``DisposableDatabase``).

    Returns (ok, rows, investigations, failures): ``failures`` are the ``CreationFailed`` errors
    whose run exists, which may be granted status-only access."""
    ok, rows, done, failures = True, [], [], []
    for path in paths:
        try:
            loaded = B.load(path)
        except B.BundleError as exc:
            ok = False
            rows.append({"bundle": str(path), "status": "refused", "code": exc.code})
            continue
        verify_db = database.connect("ca_engine")  # verify on read from a fresh connection
        try:
            inv = C.create_in_database(database.roles, loaded, verify_db=verify_db)
        except C.CreationFailed as exc:
            ok = False
            row = {"bundle": loaded.bundle_id, "status": "failed", "stage": exc.stage, "reason": exc.reason,
                   "run_id": exc.run_id, "verified": False}
            if exc.run_id:
                row["lifecycle"] = run_status(database, exc.run_id)
                failures.append(exc)
            rows.append(row)
            continue
        finally:
            verify_db.close()
        done.append(inv)
        result = json.loads(inv.result_bytes)
        rows.append({"bundle": inv.bundle_id, "status": "ok", "verified": True, "label": inv.label, "run_id": inv.run_id,
                     "outcome": result["outcome"]["status"], "mechanism": result["outcome"]["mechanism"],
                     "result_digest": inv.result_digest})
    return ok, rows, done, failures


def serve(database, investigations, grant_dir=None, port=0, ready=None, failed=()):
    """Issue a private grant for ``investigations`` and serve the read-only API until interrupted.

    The token directory is removed when serving stops, however it stops, so the token never outlives
    the server. With ``ready`` (tests), the caller owns the server and the token directory instead."""
    from ..api import server
    files = C.issue_private_grant(investigations, grant_dir, failed=failed)
    api = None
    try:
        connect = server.engine_connector(database.host, database.port, database.name, database.passwords["ca_engine"])
        api = server.build(files.grants_path, connect, port=port)
        sys.stderr.write(f"dashboard: http://127.0.0.1:{api.port}/  (read-only, synthetic data only)\n"
                         f"token file (private, removed when the server stops): {files.token_path}\n")
        if ready:
            ready(api, files)
            return api, files
        try:
            api.serve_forever()
        except KeyboardInterrupt:
            pass
        return api, files
    finally:
        if not ready:
            if api is not None:
                api.server_close()
            shutil.rmtree(files.directory, ignore_errors=True)
            if files.directory.exists():
                sys.stderr.write(f"warning: could not remove the token directory {files.directory}; delete it by hand\n")


def main(argv=None, database_factory=None):
    parser = argparse.ArgumentParser(description="Create investigations from evidence bundles (synthetic only)")
    parser.add_argument("bundles", nargs="+", type=Path, help="bundle directories")
    parser.add_argument("--offline", action="store_true", help="no database: engine-checked, not database-verified")
    parser.add_argument("--out", type=Path, help="write offline result documents here")
    parser.add_argument("--serve", action="store_true", help="serve the dashboard for the created runs until Ctrl+C")
    parser.add_argument("--grant-dir", type=Path, help="new private directory for the token (default: a temporary one)")
    parser.add_argument("--status-for-failed", action="store_true",
                        help="with --serve: also serve, status only, runs whose creation failed (never their results)")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if args.offline and (args.serve or args.grant_dir):
        parser.error("--serve and --grant-dir need database-verified runs; they cannot be combined with --offline")
    if (args.grant_dir or args.status_for_failed) and not args.serve:
        parser.error("--grant-dir and --status-for-failed are used only with --serve")
    if args.offline:
        ok, rows = _offline(args.bundles, args.out)
    else:
        if database_factory is None:
            from .disposable import DisposableDatabase
            database_factory = DisposableDatabase.from_environment
        with database_factory() as database:
            ok, rows, done, failures = create_all(database, args.bundles)
            if args.json:
                print(json.dumps(rows, indent=2))
            else:
                _print(rows)
            if args.serve:
                refused = any(r["status"] != "ok" and not r.get("run_id") for r in rows)
                if ok and done:
                    serve(database, done, args.grant_dir, args.port)
                elif args.status_for_failed and not refused and (done or failures):
                    sys.stderr.write("serving: failed runs are granted status only (no results, never verified)\n")
                    serve(database, done, args.grant_dir, args.port, failed=failures)
                else:
                    sys.stderr.write("not serving: every bundle must be created and verified first "
                                     "(--status-for-failed also serves failed runs, status only)\n")
                    return 1
            return 0 if ok else 1
    if args.json:
        print(json.dumps(rows, indent=2))
    else:
        _print(rows)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
