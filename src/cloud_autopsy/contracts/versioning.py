"""Contract version identifiers and the exact-match compatibility rule (provisional).

An identifier is ``<name>/<major>.<minor>[.<patch>][-<qualifier>]``, for example
``ca-jcs-profile/0.1-provisional``. Compatibility is exact string equality: there is no
range matching, no implicit upgrade and no coercion. Any difference is an explicit
``contract_version_mismatch``.
"""

import re

from .errors import (CONTRACT_VERSION_MALFORMED, CONTRACT_VERSION_MISMATCH, CONTRACT_VERSION_MISSING,
                     VersionError)

VERSION_FIELD = "contract_version"
_IDENTIFIER = re.compile(r"[a-z][a-z0-9-]{0,62}/(0|[1-9][0-9]{0,5})\.(0|[1-9][0-9]{0,5})"
                         r"(\.(0|[1-9][0-9]{0,5}))?(-[a-z0-9][a-z0-9.]{0,31})?")


def validate_identifier(identifier):
    """Return ``identifier`` if well formed, else raise ``contract_version_malformed``."""
    if not isinstance(identifier, str) or not _IDENTIFIER.fullmatch(identifier):
        raise VersionError(CONTRACT_VERSION_MALFORMED, "contract version identifier is not well formed")
    return identifier


def require_exact(actual, expected):
    """Accept ``actual`` only when it is exactly ``expected``."""
    validate_identifier(expected)
    validate_identifier(actual)
    if actual != expected:
        raise VersionError(CONTRACT_VERSION_MISMATCH, f"expected {expected}")
    return actual


def check_envelope(document, expected):
    """Check the ``contract_version`` field of a decoded JSON object against ``expected``."""
    if not isinstance(document, dict) or VERSION_FIELD not in document:
        raise VersionError(CONTRACT_VERSION_MISSING, f"object has no {VERSION_FIELD} field")
    return require_exact(document[VERSION_FIELD], expected)
