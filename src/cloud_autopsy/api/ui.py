"""Static assets of the read-only dashboard (CA-P2-006c), served same-origin by the loopback API.

The asset table is fixed: each served path maps to one file in this package's ``ui`` directory,
read once into memory when the server is built. No request path is ever joined to a filesystem
path, there is no directory listing and nothing is fetched from another origin. The page talks
only to the existing read-only ``/v1`` routes with a bearer token it keeps in memory.

The pages get their own Content-Security-Policy: scripts, styles and images from this origin
only, ``connect-src 'self'``, no inline script or style, no framing, no forms, and Trusted Types
enforcement so no string can be turned into HTML by the page's scripts.
"""

from pathlib import Path

UI_DIR = Path(__file__).resolve().parent / "ui"
UI_CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; "
          "font-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'; "
          "require-trusted-types-for 'script'; trusted-types 'none'")
UI_HEADERS = (("Cache-Control", "no-store"), ("X-Content-Type-Options", "nosniff"),
              ("Content-Security-Policy", UI_CSP), ("Referrer-Policy", "no-referrer"),
              ("X-Frame-Options", "DENY"), ("Cross-Origin-Opener-Policy", "same-origin"),
              ("Cross-Origin-Resource-Policy", "same-origin"), ("Permissions-Policy",
                                                                "camera=(), microphone=(), geolocation=()"))
_TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
          ".js": "text/javascript; charset=utf-8", ".svg": "image/svg+xml"}
ASSETS = {"/": "index.html", "/ui/app.css": "app.css", "/ui/app.js": "app.js", "/ui/dom.js": "dom.js",
          "/ui/motion.js": "motion.js", "/ui/topology.js": "topology.js", "/ui/views.js": "views.js",
          "/ui/model.js": "model.js", "/ui/home.js": "home.js", "/ui/icon.svg": "icon.svg"}


def load_assets():
    """{served path: (content type, bytes)} for the fixed asset table."""
    table = {}
    for path, name in ASSETS.items():
        table[path] = (_TYPES[Path(name).suffix], (UI_DIR / name).read_bytes())
    return table
