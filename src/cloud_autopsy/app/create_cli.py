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
            print(f"{r['bundle']:44} {r['status'].upper()}: {r.get('code') or r.get('reason')}"
                  + (f" at {r['stage']}" if r.get("stage") else "") + (f" (run {r['run_id']})" if r.get("run_id") else ""))


def create_all(database, paths):
    """Create each bundle in ``database`` (a ``DisposableDatabase``). Returns (ok, rows, investigations)."""
    ok, rows, done = True, [], []
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
            rows.append({"bundle": loaded.bundle_id, "status": "failed", "stage": exc.stage, "reason": exc.reason,
                         "run_id": exc.run_id})
            continue
        finally:
            verify_db.close()
        done.append(inv)
        result = json.loads(inv.result_bytes)
        rows.append({"bundle": inv.bundle_id, "status": "ok", "verified": True, "label": inv.label, "run_id": inv.run_id,
                     "outcome": result["outcome"]["status"], "mechanism": result["outcome"]["mechanism"],
                     "result_digest": inv.result_digest})
    return ok, rows, done


def serve(database, investigations, grant_dir=None, port=0, ready=None):
    """Issue a private grant for ``investigations`` and serve the read-only API until interrupted."""
    from ..api import server
    files = C.issue_private_grant(investigations, grant_dir)
    connect = server.engine_connector(database.host, database.port, database.name, database.passwords["ca_engine"])
    api = server.build(files.grants_path, connect, port=port)
    sys.stderr.write(f"dashboard: http://127.0.0.1:{api.port}/  (read-only, synthetic data only)\n"
                     f"token file (private, removed with the database at exit): {files.token_path}\n")
    if ready:
        ready(api, files)
        return api, files
    try:
        api.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        api.server_close()
    return api, files


def main(argv=None, database_factory=None):
    parser = argparse.ArgumentParser(description="Create investigations from evidence bundles (synthetic only)")
    parser.add_argument("bundles", nargs="+", type=Path, help="bundle directories")
    parser.add_argument("--offline", action="store_true", help="no database: engine-checked, not database-verified")
    parser.add_argument("--out", type=Path, help="write offline result documents here")
    parser.add_argument("--serve", action="store_true", help="serve the dashboard for the created runs until Ctrl+C")
    parser.add_argument("--grant-dir", type=Path, help="new private directory for the token (default: a temporary one)")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if args.offline and (args.serve or args.grant_dir):
        parser.error("--serve and --grant-dir need database-verified runs; they cannot be combined with --offline")
    if args.grant_dir and not args.serve:
        parser.error("--grant-dir is used only with --serve")
    if args.offline:
        ok, rows = _offline(args.bundles, args.out)
    else:
        if database_factory is None:
            from .disposable import DisposableDatabase
            database_factory = DisposableDatabase.from_environment
        with database_factory() as database:
            ok, rows, done = create_all(database, args.bundles)
            if args.json:
                print(json.dumps(rows, indent=2))
            else:
                _print(rows)
            if args.serve:
                if not ok or not done:
                    sys.stderr.write("not serving: every bundle must be created and verified first\n")
                    return 1
                serve(database, done, args.grant_dir, args.port)
            return 0 if ok else 1
    if args.json:
        print(json.dumps(rows, indent=2))
    else:
        _print(rows)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
