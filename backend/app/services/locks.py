"""Coordination between workspace resets and the requests that use the workspace."""

import threading
from collections.abc import Iterator
from contextlib import contextmanager


class ReadWriteLock:
    """Any number of readers or a single writer. A waiting writer blocks new readers.

    Not re-entrant, and not tied to a thread, so it must not be acquired twice by one request.
    """

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._readers = 0
        self._writer = False
        self._writers_waiting = 0

    @contextmanager
    def shared(self) -> Iterator[None]:
        with self._condition:
            while self._writer or self._writers_waiting:
                self._condition.wait()
            self._readers += 1
        try:
            yield
        finally:
            with self._condition:
                self._readers -= 1
                if not self._readers:
                    self._condition.notify_all()

    @contextmanager
    def exclusive(self) -> Iterator[None]:
        with self._condition:
            self._writers_waiting += 1
            try:
                while self._writer or self._readers:
                    self._condition.wait()
            finally:
                self._writers_waiting -= 1
            self._writer = True
        try:
            yield
        finally:
            with self._condition:
                self._writer = False
                self._condition.notify_all()


# Requests that read or change claims hold this shared; rebuilding the workspace holds it
# exclusively, so a demo reset never drops tables or files under an in-flight request.
WORKSPACE_LOCK = ReadWriteLock()
