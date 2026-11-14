"""Pod-log derivation (CA-P2-004g): recorded log-stream facts -> attributed lines, brackets and gaps.

Pure and deterministic; the recording converter calls it and replay calls it again. It implements the
milestone plan (docs/phase2/milestone-incident/plan.md) sections 4.3-4.6, 4.9 and 5:

**Attribution (section 5).** A stream's lines count only if all three bindings hold:
1. *watch*: when the stream was opened, the Pod watch mapped the pod name to the stream's UID, and no
   object of that name with another UID appeared from then until the stream's last line;
2. *recheck*: after the stream closed, ``GET pods/<name>`` returned the same UID, or 404 for a pod whose
   deletion the watch recorded;
3. *content*: the line's ``boot`` has a verified ``STARTED`` (seq 1) naming this pod UID and container.

**Continuity (sections 4.3-4.6).** Per container instance (pod UID, container, boot): sequence numbers
``1..k`` all observed, no conflicting duplicate, ``seq=1`` is ``STARTED``. The instance is covered to the
end of the window when its ``STOPPED`` was observed, or a line is *established* written at or after the
final watch probe (``p_end``). Anything else is a gap with a reason. Evidence is kept either way.

**Brackets (section 4.9).** Only protocol bounds:
- ``U`` = earliest receipt of any copy of the line;
- ``L`` = the pod's creation lower bound, when the pod was created during the session;
- ``L`` = ``O`` (a ``tailLines=0`` stream's send time) for every line ``k >= j+1`` of an instance, where
  ``j`` is the first line that stream delivered and line ``j+1`` carries ``synced=j`` (the handshake);
- never ``O - delta``. Without any lower bound a line has no ``observed`` time and cannot be ordered.
A handshake claim that cannot hold marks the instance ``timing_inconsistent`` (a gap).
"""

from dataclasses import dataclass, field

STREAM_MODES = ("history", "rotation", "drain")
TAIL_MODES = ("rotation", "drain")
EVIDENCE_TEMPLATES = ("CONFIG_LOADED", "POOL_EXHAUSTED")   # what becomes log_line evidence


@dataclass
class Derived:
    lines: list = field(default_factory=list)       # evidence lines (dicts), deterministic order
    gaps: list = field(default_factory=list)        # (pod uid, container, reason), sorted, unique
    instances: dict = field(default_factory=dict)   # "uid/container/boot" -> summary
    streams: dict = field(default_factory=dict)     # stream number -> attribution summary
    counts: dict = field(default_factory=dict)


def _count(counts, key, n=1):
    counts[key] = counts.get(key, 0) + n


def _content(line):
    return (line["ts"], line["synced"], line["lag_ms"], line["template"], tuple(sorted(line["fields"].items())))


def _streams(entries):
    """Group entries by stream number, keeping entry order."""
    streams = {}
    for e in entries:
        s = streams.setdefault(e["stream"], {"open": None, "lines": [], "close": None, "recheck": None,
                                             "invalid": 0, "partial": 0})
        if e["type"] == "log_open":
            s["open"] = e
        elif e["type"] == "log_line":
            if "invalid" in e["line"]:
                s["invalid"] += 1
            else:
                s["lines"].append(e)
        elif e["type"] == "log_partial":
            s["partial"] += 1
        elif e["type"] == "log_close":
            s["close"] = e
        elif e["type"] == "log_recheck":
            s["recheck"] = e
    return streams


def _watch_binding(stream, names, last_ns):
    """The Pod watch binds the stream's name to its UID from the open until ``last_ns``."""
    o = stream["open"]
    history = names.get(o["pod"], [])
    current = None
    for at, uid, kind in history:
        if at > o["sent_ns"]:
            break
        current = None if kind == "DELETED" else uid
    if current != o["uid"]:
        return "watch_unbound"
    for at, uid, kind in history:
        if o["sent_ns"] < at <= last_ns and uid != o["uid"]:
            return "name_reused"
    return None


def _recheck(stream, deleted):
    r = stream["recheck"]
    if r is None:
        return "recheck_missing"
    if r["http_status"] == 200 and r["uid"] == stream["open"]["uid"]:
        return None
    if r["http_status"] == 404 and stream["open"]["uid"] in deleted:
        return None
    return "recheck_mismatch"


def derive(entries, pods, names, p_end_ns):
    """``entries``: the recorded pod-log entries (absolute ns). ``pods``: {uid: {"name", "containers",
    "created_lower_ns" | None, "restarts_first", "restarts_max", "deleted"}} for every pod the watch saw
    in the window. ``names``: {name: [(received_ns, uid, "ADDED" | "MODIFIED" | "DELETED" | "LISTED")]},
    sorted. ``p_end_ns``: the send time of the final Pod probe (the window's end)."""
    out = Derived()
    deleted = {uid for uid, p in pods.items() if p.get("deleted")}
    streams = _streams(entries)
    gaps = set()

    def gap(uid, container, reason):
        gaps.add((uid, container, reason))

    # 1. Attribution of each stream (watch binding and recheck); content binding comes per boot.
    usable = {}
    for number in sorted(streams):
        s = streams[number]
        o = s["open"]
        if o is None or o["mode"] not in STREAM_MODES:
            _count(out.counts, "stream_without_open")
            continue
        uid, container = o["uid"], o["container"]
        if o["http_status"] != 200:
            out.streams[number] = {"uid": uid, "container": container, "mode": o["mode"], "used": False,
                                   "reason": "open_failed"}
            continue
        last_ns = max([e["received_ns"] for e in s["lines"]] + [o["sent_ns"]])
        reason = _watch_binding(s, names, last_ns) or _recheck(s, deleted)
        if uid not in pods or container not in pods[uid]["containers"]:
            reason = reason or "pod_unknown"
        if s["invalid"]:
            gap(uid, container, "unparseable_line")
            _count(out.counts, "lines_invalid", s["invalid"])
        if s["partial"]:
            _count(out.counts, "lines_partial", s["partial"])
        out.streams[number] = {"uid": uid, "container": container, "mode": o["mode"], "used": reason is None,
                               "reason": reason}
        if reason is not None:
            if uid in pods:
                gap(uid, container, reason)
            _count(out.counts, f"stream_{reason}")
            continue
        usable[number] = s

    # 2. Content binding: a boot is verified by a STARTED (seq 1) naming this pod UID and container.
    verified = set()
    for s in usable.values():
        o = s["open"]
        for e in s["lines"]:
            line = e["line"]
            if line["seq"] == 1 and line["template"] == "STARTED" and line["fields"].get("pod_uid") == o["uid"] \
                    and line["fields"].get("container") == o["container"]:
                verified.add((o["uid"], o["container"], line["boot"]))

    # 3. Copies of each line per instance; conflicts; receipt order per stream.
    instances = {}
    for number, s in sorted(usable.items()):
        o = s["open"]
        for e in s["lines"]:
            line = e["line"]
            key = (o["uid"], o["container"], line["boot"])
            if key not in verified:
                gap(o["uid"], o["container"], "boot_unverified")
                _count(out.counts, "lines_unattributed")
                continue
            inst = instances.setdefault(key, {"copies": {}, "conflict": False})
            copy = inst["copies"].setdefault(line["seq"], {"content": _content(line), "line": line,
                                                           "received": [], "streams": []})
            if copy["content"] != _content(line):
                inst["conflict"] = True
            copy["received"].append(e["received_ns"])
            copy["streams"].append(number)

    # 4. Handshake lower bounds and timing consistency, per instance.
    for key, inst in sorted(instances.items()):
        uid, container, boot = key
        copies = inst["copies"]
        seqs = sorted(copies)
        info = {"pod": pods[uid]["name"], "first_seq": seqs[0], "last_seq": seqs[-1], "lines": len(seqs),
                "stopped": False, "covered_to_end": False, "handshake_bounds": 0, "reasons": []}
        reasons = info["reasons"]
        if inst["conflict"]:
            reasons.append("identity_conflict")
        if seqs != list(range(1, seqs[-1] + 1)):
            reasons.append("sequence_gap")
        if copies.get(1, {}).get("line", {}).get("template") != "STARTED":
            reasons.append("started_missing")
        stopped = [q for q in seqs if copies[q]["line"]["template"] == "STOPPED"]
        if stopped:
            info["stopped"] = True
            if stopped != [seqs[-1]]:
                reasons.append("lines_after_stopped")
        for q in seqs:
            synced = copies[q]["line"]["synced"]
            if synced is not None and (q == 1 or synced != q - 1):
                reasons.append("timing_inconsistent")
                break
        handshake = {q: None for q in seqs}   # lower bounds established by the handshake only
        for number, s in sorted(usable.items()):
            o = s["open"]
            mine = [e for e in s["lines"] if (o["uid"], o["container"], e["line"]["boot"]) == key]
            if o["mode"] not in TAIL_MODES or not mine:
                continue
            # The order a stream delivers lines in is the order they were appended.
            delivered = [e["line"]["seq"] for e in mine]
            if delivered != sorted(delivered):
                reasons.append("timing_inconsistent")
            j = mine[0]["line"]["seq"]
            follower = copies.get(j + 1)
            if follower is None or follower["line"]["synced"] != j:
                continue
            if min(follower["received"]) < min(copies[j]["received"]):
                reasons.append("timing_inconsistent")  # a line claims to follow one that arrived later
                continue
            info["handshake_bounds"] += 1
            for q in seqs:
                if q >= j + 1:
                    handshake[q] = o["sent_ns"] if handshake[q] is None else max(handshake[q], o["sent_ns"])
        established_after_end = any(h is not None and h >= p_end_ns for h in handshake.values())
        created = pods[uid].get("created_lower_ns")
        for q in seqs:
            upper = min(copies[q]["received"])
            candidates = [b for b in (created, handshake[q]) if b is not None]
            low = max(candidates) if candidates else None
            if low is not None and low >= upper:
                reasons.append("timing_inconsistent")
                low = None
            copies[q]["bracket"] = (low, upper)
        info["covered_to_end"] = info["stopped"] or established_after_end
        if not info["covered_to_end"]:
            reasons.append("tail_unproven")
        for reason in sorted(set(reasons)):
            gap(uid, container, reason)
        info["reasons"] = sorted(set(reasons))
        out.instances[f"{uid}/{container}/{boot}"] = info
        for q in seqs:
            line = copies[q]["line"]
            if line["template"] in EVIDENCE_TEMPLATES:
                low, up = copies[q]["bracket"]
                out.lines.append({"uid": uid, "pod": pods[uid]["name"], "container": container, "boot": boot,
                                  "seq": q, "ts": line["ts"], "template": line["template"],
                                  "fields": dict(line["fields"]), "lower_ns": low, "upper_ns": up})

    # 5. Every pod and container the watch saw must have its instances: none missing, none restarted unseen.
    for uid, pod in sorted(pods.items()):
        for container in pod["containers"]:
            boots = [k for k in instances if k[:2] == (uid, container)]
            if not boots:
                gap(uid, container, "not_collected")
            elif pod.get("restarts_first", 0) > 0:
                gap(uid, container, "restarted_before_attach")
            elif len(boots) < pod.get("restarts_max", 0) + 1:
                gap(uid, container, "instance_missing")

    out.gaps = sorted(gaps)
    out.lines.sort(key=lambda d: (d["uid"], d["container"], d["boot"], d["seq"]))
    out.counts = dict(sorted(out.counts.items()))
    return out


# ------------------------------------------------------------------- recording 0.5: strict entry checks

_LOG_ENTRY_KEYS = {
    "log_open": {"seq", "type", "stream", "pod", "uid", "container", "mode", "sent_ns", "http_status", "error"},
    "log_line": {"seq", "type", "stream", "received_ns", "line"},
    "log_partial": {"seq", "type", "stream", "at_ns"},
    "log_close": {"seq", "type", "stream", "at_ns", "code"},
    "log_recheck": {"seq", "type", "stream", "sent_ns", "received_ns", "http_status", "uid"},
}
_LINE_KEYS = {"ts", "boot", "seq", "synced", "lag_ms", "template", "fields"}


class LogEntryError(ValueError):
    pass


def check_line(line):
    """A recorded sanitized line must be exactly what ``logline.sanitize`` can produce: nothing more."""
    from ..collector import logline
    import re
    if not isinstance(line, dict):
        raise LogEntryError("a log line must be an object")
    if set(line) == {"invalid"}:
        if line["invalid"] not in ("not_bytes", "not_ascii", "timestamp", "too_long", "envelope"):
            raise LogEntryError("unknown invalid-line code")
        return
    if set(line) != _LINE_KEYS:
        raise LogEntryError("a log line has exactly the sanitized fields")
    if not isinstance(line["ts"], str) or not re.fullmatch(logline._TS, line["ts"], re.ASCII) \
            or not isinstance(line["boot"], str) or not re.fullmatch(r"[0-9a-f]{8}", line["boot"], re.ASCII):
        raise LogEntryError("a log line needs a timestamp and a boot")
    for key, low in (("seq", 1), ("synced", 0), ("lag_ms", 0)):
        value = line[key]
        if key != "seq" and value is None:
            continue
        if type(value) is not int or not low <= value <= logline.MAX_SEQ:
            raise LogEntryError(f"{key} must be an integer in range")
    if (line["synced"] is None) != (line["lag_ms"] is None):
        raise LogEntryError("synced and lag_ms come together")
    template, fields = line["template"], line["fields"]
    if not isinstance(fields, dict):
        raise LogEntryError("fields must be an object")
    if template is None:
        if fields:
            raise LogEntryError("an unmatched line carries no fields")
        return
    spec = logline._COMPILED.get(template)
    if spec is None or set(fields) != {k for k, _ in spec} \
            or not all(isinstance(fields[k], str) and p.fullmatch(fields[k]) for k, p in spec):
        raise LogEntryError("a matched line carries exactly its template's typed fields")


def check_entries(entries):
    """Validate the recorded ``pod_logs`` stream: shapes, numbering, one open/close per stream, order."""
    from ..collector import client as cl, podlogs
    streams = {}
    for i, e in enumerate(entries, 1):
        if not isinstance(e, dict) or e.get("type") not in _LOG_ENTRY_KEYS or set(e) != _LOG_ENTRY_KEYS[e["type"]]:
            raise LogEntryError("a log entry has an unknown type or fields")
        if e["seq"] != i or type(e["stream"]) is not int or not 1 <= e["stream"] <= 1_000_000:
            raise LogEntryError("log entries are numbered in order and name their stream")
        s = streams.setdefault(e["stream"], {"open": False, "close": False, "recheck": False})
        kind = e["type"]
        if kind == "log_open":
            if s["open"] or e["mode"] not in STREAM_MODES or not isinstance(e["pod"], str) \
                    or not cl.POD_NAME.fullmatch(e["pod"]) or not isinstance(e["container"], str) \
                    or not cl.CONTAINER_NAME.fullmatch(e["container"]) or not isinstance(e["uid"], str) \
                    or not 0 < len(e["uid"]) <= 128 or not e["uid"].isprintable():
                raise LogEntryError("a stream opens once, with a pod, UID, container and mode")
            if e["http_status"] is not None and (type(e["http_status"]) is not int or not 100 <= e["http_status"] <= 599):
                raise LogEntryError("http_status must be an HTTP status")
            if e["error"] is not None and (not isinstance(e["error"], str) or len(e["error"]) > 64):
                raise LogEntryError("error must be a short code")
            s["open"] = True
        elif not s["open"]:
            raise LogEntryError("a stream's entries follow its open")
        elif kind == "log_line":
            if s["close"]:
                raise LogEntryError("no line after a stream's close")
            check_line(e["line"])
        elif kind == "log_close":
            if s["close"] or e["code"] not in podlogs.CLOSE_CODES:
                raise LogEntryError("a stream closes once, with a known code")
            s["close"] = True
        elif kind == "log_recheck":
            if not s["close"] or s["recheck"]:
                raise LogEntryError("a recheck follows the close, once")
            if e["http_status"] is not None and (type(e["http_status"]) is not int or not 100 <= e["http_status"] <= 599):
                raise LogEntryError("http_status must be an HTTP status")
            if e["uid"] is not None and (not isinstance(e["uid"], str) or not 0 < len(e["uid"]) <= 128):
                raise LogEntryError("uid must be a short string")
            if e["sent_ns"] > e["received_ns"]:
                raise LogEntryError("a recheck is received after it is sent")
            s["recheck"] = True
    for s in streams.values():
        if not s["close"]:
            raise LogEntryError("every stream is closed")
