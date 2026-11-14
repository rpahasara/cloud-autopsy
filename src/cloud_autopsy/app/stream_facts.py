"""Sanitized facts about a recorded list + watch stream (CA-P2-004g, Events-proof investigation).

Read-only diagnostics over a collector recording (0.4-0.6): for each resource and segment, what the watch
delivered (events and bookmarks, by type and resourceVersion), the probes and whether each was proven, the
watch opens and disconnects, and how the segment ended. Only resourceVersions, counts, codes and session-clock
offsets are reported -- never object content. It changes no conversion and no report.
"""

from pathlib import Path

from ..contracts import resourceversion as rv
from . import k8s_recording as K
from . import k8s_watch_recording as W


def facts(recording_dir):
    root = Path(recording_dir)
    manifest, _ = K._read_manifest(root)
    out = {}
    for stream in manifest["streams"]:
        if stream["resource"] == "pod_logs":
            continue
        entries = W._entries(root, stream)
        segments = []
        for e in entries:
            if e["type"] == "list":
                segments.append({"segment": e["segment"], "list": e["outcome"],
                                 "list_rv": e["collection_resource_version"], "watch_opens": 0, "disconnects": [],
                                 "events": 0, "bookmarks": 0, "last_delivered": None, "last_delivered_at_ms": None,
                                 "probes": [], "end": None})
                continue
            seg = segments[-1]
            if e["type"] == "watch_open":
                seg["watch_opens"] += 1
            elif e["type"] == "disconnect":
                seg["disconnects"].append(e["code"])
            elif e["type"] in ("event", "bookmark"):
                seg["events" if e["type"] == "event" else "bookmarks"] += 1
                seg["last_delivered"] = [e["resource_version"], e.get("event", "BOOKMARK")]
                seg["last_delivered_at_ms"] = e["received_ns"] // 1_000_000
            elif e["type"] == "probe":
                seg["probes"].append({"rv": e["resource_version"], "sent_at_ms": e["sent_ns"] // 1_000_000,
                                      "status": e["http_status"]})
            elif e["type"] == "end":
                seg["end"] = e["code"]
        for seg in segments:
            delivered = seg["last_delivered"][0] if seg["last_delivered"] else seg["list_rv"]
            for probe in seg["probes"]:
                probe["proven"] = bool(probe["rv"] and delivered and rv.is_valid(probe["rv"])
                                       and rv.at_least(delivered, probe["rv"]))
            proven = [p for p in seg["probes"] if p["proven"]]
            seg["last_proven_probe"] = proven[-1] if proven else None
            seg["final_probe"] = seg["probes"][-1] if seg["probes"] else None
            seg["probes_total"], seg["probes_unproven"] = len(seg["probes"]), len(seg["probes"]) - len(proven)
            seg["probes"] = seg["probes"][-3:]   # the last three, to keep the output short
        out[stream["resource"]] = segments
    return out
