"""Coordination between requests that change the same claim.

Two things are coordinated here: a workspace reset never runs under an in-flight request, and a
state transition is decided against a row no other request can be changing at the same time.
"""

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from typing import TypeVar

from sqlalchemy.orm import Session


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


T = TypeVar("T")


def locked(session: Session, instance: T) -> T:
    """Re-read this row, holding it until the transaction ends, and return it.

    Every state transition in this system is guarded by the state the row is already in: a claim
    that is approved cannot be approved again, a closed question takes no further answer. Reading
    that state without holding the row lets two requests pass the same guard and both act, which
    puts two human decisions on the record where a person made one. Locking the row first makes
    the second request wait for the first to finish and then see what it did.

    On PostgreSQL this is SELECT ... FOR UPDATE. SQLite has no row locks and serialises writers
    instead; the re-read still returns the committed state, which is what the guard needs.
    """
    session.refresh(instance, with_for_update=True)
    return instance
