"""Console-script entry for tibet-nc.

Declared in pyproject.toml: `tibet-nc = "tibet_nc.cli:main"`. Mirrors the daemon's
`__main__` block so `tibet-nc` (installed script) and `python -m tibet_nc.daemon`
behave identically: start the Matrix-E2EE command-room daemon (restricted PTY +
L4 Airlock + TIBET token per command).
"""
from __future__ import annotations

import asyncio

from tibet_nc.daemon import TibetNCDaemon, log


def main() -> None:
    """Run the tibet-nc Matrix E2EE command-room daemon."""
    daemon = TibetNCDaemon()
    try:
        asyncio.run(daemon.run())
    except KeyboardInterrupt:
        daemon.shutdown()
    except Exception as e:  # noqa: BLE001 — top-level guard, log + clean shutdown
        log(f"FATAL: {e}")
        daemon.shutdown()


if __name__ == "__main__":
    main()
