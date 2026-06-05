"""
tibet-nc — Secure remote shell via Matrix E2EE.

    *** PRE-ALPHA — NOT PRODUCTION READY ***

No ports. No TCP surface. No SSH daemon.
Every command is a TIBET token with L4 Airlock verification.

Transport: Matrix E2EE (end-to-end encrypted)
Auth:      TIBET identity + Matrix user verification
Exec:      Restricted PTY with blocked command patterns
Audit:     Full TIBET provenance chain per command

Status: Pre-alpha (v0.1.0a1) — API and protocol WILL change.
"""

__version__ = "0.1.0a1"
__status__ = "Pre-Alpha"

# Will be populated as modules stabilize
__all__: list[str] = []
