"""Run lifecycle status through ``ca.run_status`` (migration 0005, CA-P2-004b, provisional).

Read as ``ca_engine``. Only the run's state, a fixed failure reason (failed runs) and whether the
lease expired (sealing runs) are returned. A status is lifecycle metadata, never a verified result:
callers must not present any run as verified on the strength of its status.
"""

import re
from dataclasses import dataclass

STATES = frozenset({"collecting", "sealing", "sealed", "failed", "cancelled"})
_REASON = re.compile(r"seal:[a-z][a-z0-9_]{0,63}|unspecified", re.ASCII)


class StatusInvalid(RuntimeError):
    """The view returned something outside its documented shape; nothing is passed through."""


@dataclass(frozen=True)
class RunStatus:
    run_id: str
    state: str
    failure_reason: str = None    # failed runs only
    lease_expired: bool = None    # sealing runs only

    def to_record(self):
        return {"state": self.state, "failure_reason": self.failure_reason, "lease_expired": self.lease_expired}


def load_status(engine_db, run_id):
    """The run's ``RunStatus``, or None when no such run exists."""
    row = engine_db.one("SELECT state, failure_reason, lease_expired FROM ca.run_status "
                        "WHERE run_id = CAST(:r AS uuid)", r=run_id)
    if row is None:
        return None
    state, reason, expired = row
    if state not in STATES or (reason is not None and not (state == "failed" and _REASON.fullmatch(reason))) \
            or (expired is not None and (state != "sealing" or not isinstance(expired, bool))):
        raise StatusInvalid("run status outside the documented shape")
    return RunStatus(run_id, state, reason if state == "failed" else None, expired if state == "sealing" else None)
