"""Isolated, read-only Kubernetes collector (CA-P2-004e, provisional, synthetic-only).

Standard library only. It lists Pods, Deployments, ReplicaSets and Events in one namespace of a
disposable local cluster through a fixed allowlist of HTTPS GET requests, projects every object
to an allowlist in memory, and writes a sanitized ``ca-k8s-recording/0.3-provisional`` recording,
a bundle and a collection report. No raw response, credential or Event message is persisted.
See docs/phase2/ca-p2-004/ca-p2-004e.md.
"""
