"""Run office work inline or on a daemon thread.

Eager mode is for tests. It calls the same function the thread would call.
"""

from __future__ import annotations

import logging
import threading

from office.config import Config

log = logging.getLogger("office")


def submit(config: Config, label: str, fn) -> None:
    if config.eager:
        fn()
        return

    def guarded():
        try:
            fn()
        except Exception:
            log.exception("background task %s failed", label)

    threading.Thread(target=guarded, name=f"office-{label}", daemon=True).start()
