"""A process says it is alive every few seconds, from a thread of its own.

A thread, not a task: the crawler embeds postings and the worker renders PDFs
on the event loop, and a heartbeat that waited for them would go quiet for as
long as they ran, which would read as the machine being away. The thread keeps
its own synchronous connection, so it never waits for the event loop.
"""

from __future__ import annotations

import threading
import uuid

import psycopg

from kernel.config import Unit
from kernel.logging import get_logger

log = get_logger(__name__)

# A row nobody has refreshed in this long belongs to a process long gone.
_FORGET_AFTER = "1 day"


class Heartbeat:
    """Refreshes this process's row until stopped, then deletes it."""

    def __init__(self, dsn: str, unit: Unit, *, interval_seconds: float) -> None:
        self._dsn = dsn
        self._unit = unit
        self._interval = interval_seconds
        self._id = uuid.uuid4()
        self._stopping = threading.Event()
        self._thread = threading.Thread(target=self._run, name=f"heartbeat-{unit}", daemon=True)

    @property
    def process_id(self) -> uuid.UUID:
        """This process's row: a restart is a new one."""
        return self._id

    def start(self) -> None:
        self._thread.start()
        log.info("presence.heartbeat_started", unit=str(self._unit), process_id=str(self._id))

    def stop(self) -> None:
        """Stop beating and remove the row, so the process reads as gone at once."""
        self._stopping.set()
        self._thread.join(timeout=self._interval + 5)
        try:
            with psycopg.connect(self._dsn, autocommit=True) as connection:
                connection.execute("DELETE FROM presence.process WHERE id = %s", (self._id,))
        except psycopg.Error:
            log.warning("presence.heartbeat_not_removed", unit=str(self._unit), exc_info=True)

    def _run(self) -> None:
        connection: psycopg.Connection | None = None
        while not self._stopping.is_set():
            try:
                if connection is None or connection.closed:
                    connection = psycopg.connect(self._dsn, autocommit=True)
                self._beat(connection)
            except psycopg.Error:
                # The database may be away too (a tunnel down); the next beat
                # reconnects. Logged, so a heartbeat that never lands is seen.
                log.warning("presence.heartbeat_failed", unit=str(self._unit), exc_info=True)
                if connection is not None:
                    connection.close()
                connection = None
            self._stopping.wait(self._interval)
        if connection is not None:
            connection.close()

    def _beat(self, connection: psycopg.Connection) -> None:
        connection.execute(
            "INSERT INTO presence.process (id, unit, started_at, seen_at) "
            "VALUES (%s, %s, now(), now()) "
            "ON CONFLICT (id) DO UPDATE SET seen_at = now()",
            (self._id, str(self._unit)),
        )
        connection.execute(
            "DELETE FROM presence.process WHERE seen_at < now() - %s::interval", (_FORGET_AFTER,)
        )
