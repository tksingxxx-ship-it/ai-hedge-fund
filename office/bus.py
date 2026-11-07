"""In-process fan-out for server-sent events.

Listeners see the same rows that were committed to the events table.
Nothing is generated on a timer.
"""

from __future__ import annotations

import queue
import threading

_LOCK = threading.Lock()
_LISTENERS: list[queue.Queue] = []


def subscribe() -> queue.Queue:
    listener: queue.Queue = queue.Queue(maxsize=400)
    with _LOCK:
        _LISTENERS.append(listener)
    return listener


def unsubscribe(listener: queue.Queue) -> None:
    with _LOCK:
        if listener in _LISTENERS:
            _LISTENERS.remove(listener)


def publish(event: dict) -> None:
    with _LOCK:
        listeners = list(_LISTENERS)
    for listener in listeners:
        try:
            listener.put_nowait(event)
        except queue.Full:
            try:
                listener.get_nowait()
            except queue.Empty:
                pass
            try:
                listener.put_nowait(event)
            except queue.Full:
                pass
