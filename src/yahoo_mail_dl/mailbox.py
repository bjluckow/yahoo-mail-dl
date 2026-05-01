"""YahooMailbox — high-level interface for bulk email download."""

from __future__ import annotations

import email
import email.policy
import logging
import queue
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from email.message import EmailMessage
from typing import Generator

from . import constants as C
from .connection import IMAPConnection
from .filters import FilterSpec
from .search import search_uids

log = logging.getLogger(__name__)

# Sentinel to signal a worker is done
_DONE = object()


class YahooMailbox:
    """Context manager for bulk-downloading from Yahoo/AOL mailboxes.

    Usage::

        with YahooMailbox(host="export.imap.aol.com",
                          username="user@aol.com",
                          password="xxxx") as mb:
            for folder, msg in mb.fetch(since=date(2020, 1, 1)):
                print(folder, msg["Subject"])
    """

    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        *,
        port: int = C.IMAP_PORT,
        timeout: float = C.IMAP_TIMEOUT_SECONDS,
        max_retries: int = C.MAX_RETRIES,
        backoff_base: float = C.RETRY_BACKOFF_BASE,
        backoff_max: float = C.RETRY_BACKOFF_MAX,
        fetch_batch_size: int = C.FETCH_BATCH_SIZE,
        search_window_days: int = C.SEARCH_WINDOW_DAYS,
        search_delay: float = C.SEARCH_DELAY_SECONDS,
        fetch_delay: float = C.FETCH_DELAY_SECONDS,
    ) -> None:
        self.host = host
        self.username = username
        self.password = password
        self.port = port
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.backoff_max = backoff_max
        self.fetch_batch_size = fetch_batch_size
        self.search_window_days = search_window_days
        self.search_delay = search_delay
        self.fetch_delay = fetch_delay

        # Primary connection used for listing folders / sequential fetch
        self._conn: IMAPConnection | None = None

    def _make_connection(self) -> IMAPConnection:
        """Create a new connection with our stored settings."""
        return IMAPConnection(
            self.host,
            self.username,
            self.password,
            port=self.port,
            timeout=self.timeout,
            max_retries=self.max_retries,
            backoff_base=self.backoff_base,
            backoff_max=self.backoff_max,
        )

    # -- context manager --

    def __enter__(self) -> YahooMailbox:
        self._conn = self._make_connection()
        self._conn.connect()
        return self

    def __exit__(self, *exc: object) -> None:
        if self._conn:
            self._conn.disconnect()
            self._conn = None

    # -- public API --

    def list_folders(self) -> list[str]:
        """List all folders in the mailbox."""
        assert self._conn is not None
        return self._conn.list_folders()

    def fetch(
        self,
        *,
        since: date | None = None,
        until: date | None = None,
        folders: list[str] | None = None,
        seen: set[str] | None = None,
        filters: FilterSpec | None = None,
        workers: int = C.DEFAULT_WORKERS,
    ) -> Generator[tuple[str, EmailMessage], None, None]:
        """Yield (folder_name, EmailMessage) for all matching messages.

        Args:
            since: Only fetch messages on or after this date.
            until: Only fetch messages before this date.
            folders: Folder names to fetch. None = all folders.
            seen: Set of Message-IDs to skip (for resume support).
                  The caller owns persistence of this set.
            filters: Client-side address filters. None = no filtering.
            workers: Number of concurrent folder-download threads.
                     1 = sequential (default). Max = constants.MAX_WORKERS.
        """
        assert self._conn is not None
        seen = seen or set()
        filters = filters or FilterSpec()
        workers = max(1, min(workers, C.MAX_WORKERS))

        target_folders = folders or self._conn.list_folders()
        log.info(
            "Fetching %d folders with %d worker(s)", len(target_folders), workers
        )

        if workers == 1:
            yield from self._fetch_sequential(target_folders, since, until, seen, filters)
        else:
            yield from self._fetch_threaded(
                target_folders, since, until, seen, filters, workers
            )

    # -- sequential path --

    def _fetch_sequential(
        self,
        folders: list[str],
        since: date | None,
        until: date | None,
        seen: set[str],
        filters: FilterSpec,
    ) -> Generator[tuple[str, EmailMessage], None, None]:
        assert self._conn is not None
        for folder in folders:
            yield from self._fetch_folder(self._conn, folder, since, until, seen, filters)

    # -- threaded path --

    def _fetch_threaded(
        self,
        folders: list[str],
        since: date | None,
        until: date | None,
        seen: set[str],
        filters: FilterSpec,
        workers: int,
    ) -> Generator[tuple[str, EmailMessage], None, None]:
        result_queue: queue.Queue[tuple[str, EmailMessage] | object] = queue.Queue(
            maxsize=workers * self.fetch_batch_size
        )
        active_workers = len(folders)

        def _worker(folder: str) -> None:
            nonlocal active_workers
            conn = self._make_connection()
            try:
                conn.connect()
                for item in self._fetch_folder(conn, folder, since, until, seen, filters):
                    result_queue.put(item)
            except Exception:
                log.exception("Worker error on folder %r", folder)
            finally:
                conn.disconnect()
                result_queue.put(_DONE)

        with ThreadPoolExecutor(max_workers=workers) as pool:
            for folder in folders:
                pool.submit(_worker, folder)

            done_count = 0
            while done_count < active_workers:
                item = result_queue.get()
                if item is _DONE:
                    done_count += 1
                else:
                    yield item  # type: ignore[misc]

    # -- per-folder fetch (used by both paths) --

    def _fetch_folder(
        self,
        conn: IMAPConnection,
        folder: str,
        since: date | None,
        until: date | None,
        seen: set[str],
        filters: FilterSpec,
    ) -> Generator[tuple[str, EmailMessage], None, None]:
        """Fetch all messages from a single folder."""
        try:
            conn.select_folder(folder)
        except Exception:
            log.warning("Skipping inaccessible folder %r", folder)
            return

        uids = search_uids(
            conn,
            since=since,
            until=until,
            window_days=self.search_window_days,
            search_delay=self.search_delay,
        )
        log.info("Folder %r: %d UIDs to fetch", folder, len(uids))

        # Fetch in batches
        for batch_start in range(0, len(uids), self.fetch_batch_size):
            batch = uids[batch_start : batch_start + self.fetch_batch_size]
            uid_range = b",".join(batch)

            status, data = conn.execute(
                "uid", "FETCH", uid_range, "(RFC822)"
            )

            for response_part in data:
                if not isinstance(response_part, tuple):
                    continue

                raw_email = response_part[1]
                if not isinstance(raw_email, bytes):
                    continue

                try:
                    msg = email.message_from_bytes(
                        raw_email, policy=email.policy.default
                    )
                except Exception:
                    log.warning("Failed to parse message in %r, skipping", folder)
                    continue

                message_id = msg.get("Message-ID", "")
                if message_id in seen:
                    log.debug("Skipping already-seen %s", message_id)
                    continue

                if not filters.matches(msg):
                    log.debug("Filtered out %s", message_id)
                    continue

                seen.add(message_id)
                yield folder, msg

            # Rate limit between batches
            if batch_start + self.fetch_batch_size < len(uids):
                time.sleep(self.fetch_delay)