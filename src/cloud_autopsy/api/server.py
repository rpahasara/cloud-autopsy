"""Run the local read-only investigation API against a disposable synthetic database.

  python -m cloud_autopsy.api.server --grants /private/dir/api-grants.json [--port 8765]

Database settings come from the environment, as for the other local tools:
  CA_PG_HOST (127.0.0.1), CA_PG_PORT (55432), CA_API_DATABASE (required), and the ``ca_engine``
  password file in CA_PG_SECRET_DIR. The API connects only as ``ca_engine`` (read-only by
  default, sealed-only views), opens one connection per request and closes it afterwards.
"""

import argparse
import os
import sys
from pathlib import Path

from ..db import ingest, results
from ..db.adapter import Database, DbError, Endpoint
from . import grants as grants_module
from . import ui
from .service import ApiService, BackendDown, Unavailable, Unverifiable
from .transport import LOOPBACK, LoopbackServer


def database_backend(connect):
    """Loader and readiness probe over ``connect()``, which returns a new ``ca_engine`` Database.

    The loader returns only what ``results.load_verified_result`` returns; every failure is
    mapped to an error type and no row is ever passed through unverified."""

    def load_verified(run_id):
        try:
            db = connect()
        except DbError:
            raise BackendDown() from None
        try:
            return results.load_verified_result(db, run_id)
        except results.StoredResultUnavailable:
            raise Unavailable() from None
        except results.StoredResultInvalid as exc:
            raise Unverifiable(exc.code) from None
        except DbError:
            raise BackendDown() from None
        finally:
            db.close()

    def check_ready():
        try:
            db = connect()
        except DbError:
            raise BackendDown() from None
        try:
            ingest.check_environment(db)
            if db.one("SELECT current_setting('default_transaction_read_only')")[0] != "on":
                raise BackendDown()
        except (DbError, ingest.EnvironmentMismatch):
            raise BackendDown() from None
        finally:
            db.close()

    return load_verified, check_ready


def engine_connector(host, port, database, password):
    def connect():
        return Database(Endpoint(host, int(port), database), "ca_engine", password,
                        application_name="cloud-autopsy-api")
    return connect


def build(grants_path, connect, port=0, quiet=False, dashboard=True):
    load_verified, check_ready = database_backend(connect)
    service = ApiService(grants_module.load(grants_path), load_verified, check_ready,
                         ui=ui.load_assets() if dashboard else None)
    return LoopbackServer(service, port, quiet=quiet)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Local read-only investigation API (127.0.0.1 only)")
    parser.add_argument("--grants", required=True, help="grants file outside any Git working tree")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    secret_dir, database = os.environ.get("CA_PG_SECRET_DIR"), os.environ.get("CA_API_DATABASE")
    if not secret_dir or not database:
        parser.error("CA_PG_SECRET_DIR and CA_API_DATABASE must be set")
    password = (Path(secret_dir) / "ca_engine.password").read_text(encoding="ascii").strip()
    connect = engine_connector(os.environ.get("CA_PG_HOST", LOOPBACK), os.environ.get("CA_PG_PORT", "55432"),
                               database, password)
    server = build(args.grants, connect, args.port)
    sys.stderr.write(f"api listening on http://{LOOPBACK}:{server.port} (read-only, synthetic data only); "
                     f"dashboard at http://{LOOPBACK}:{server.port}/\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
