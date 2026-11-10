"""Local, read-only investigation API (CA-P2-006b). Provisional; synthetic development data only.

``grants``  locally provisioned bearer tokens (stored only as SHA-256) with explicit per-run grants.
``service`` transport-independent request handling: validation, authentication, run-level
            authorization, verify-on-read through ``db.results.load_verified_result``, and
            size-limited canonical JSON responses.
``server``  a loopback-only HTTP server on the standard library (``http.server``).

There are no write endpoints. A result is served only after full verification succeeds; on any
verification failure the response is an error code, never database rows.
"""

API_VERSION = "ca-api/0.1-provisional"
