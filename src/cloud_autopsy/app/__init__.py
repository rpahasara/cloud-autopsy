"""Local application layer (CA-P2-005a): wires synthetic inputs, the PostgreSQL layer and the engine.

This package may perform local I/O (reading the per-session secret directory, writing result
files). It talks only to a disposable, loopback, synthetic-only database. No collectors, no
cluster access, no external model calls and no remediation.
"""
