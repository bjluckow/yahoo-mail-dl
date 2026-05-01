"""IMAP connection wrapper with transparent reconnect and retry."""

from __future__ import annotations

import imaplib
import logging
import socket
import ssl
import time
from typing import TYPE_CHECKING

from . import constants as C

if TYPE_CHECKING:
    pass

log = logging.getLogger(__name__)


class ConnectionError(Exception):
    """Raised when connection cannot be established after retries."""


class IMAPConnection:
    """Manages a single IMAP connection with auto-reconnect.

    Not thread-safe — each thread should own its own instance.
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
    ) -> None:
        self.host = host
        self.username = username
        self.password = password
        self.port = port
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.backoff_max = backoff_max

        self._imap: imaplib.IMAP4_SSL | None = None
        self._selected_folder: str | None = None

    # -- lifecycle --

    def connect(self) -> None:
        """Establish connection and authenticate."""
        self.disconnect()
        log.info("Connecting to %s:%d as %s", self.host, self.port, self.username)

        ctx = ssl.create_default_context()
        self._imap = imaplib.IMAP4_SSL(
            self.host, self.port, ssl_context=ctx, timeout=self.timeout
        )
        self._imap.login(self.username, self.password)
        self._selected_folder = None
        log.info("Connected and authenticated")

    def disconnect(self) -> None:
        """Close connection gracefully, ignoring errors."""
        if self._imap is None:
            return
        try:
            self._imap.logout()
        except Exception:
            pass
        self._imap = None
        self._selected_folder = None

    def reconnect(self) -> None:
        """Reconnect, re-selecting the previously selected folder."""
        folder = self._selected_folder
        self.connect()
        if folder:
            self.select_folder(folder)

    @property
    def imap(self) -> imaplib.IMAP4_SSL:
        if self._imap is None:
            raise ConnectionError("Not connected")
        return self._imap

    # -- folder operations --

    def list_folders(self) -> list[str]:
        """Return list of folder names."""
        status, data = self.imap.list()
        if status != "OK":
            raise ConnectionError(f"LIST failed: {status}")

        folders: list[str] = []
        for item in data:
            if not isinstance(item, bytes):
                continue
            line = item.decode()
            # IMAP LIST response: (\\flags) "delimiter" "name"
            # The folder name is the last quoted string or the tail after the last space
            parts = line.rsplit('" ', 1)
            if len(parts) == 2:
                name = parts[1].strip().strip('"')
                folders.append(name)
        return folders

    def select_folder(self, folder: str) -> int:
        """SELECT a folder, returning the message count."""
        status, data = self.imap.select(f'"{folder}"')
        if status != "OK":
            raise ConnectionError(f"SELECT {folder!r} failed: {status}")
        self._selected_folder = folder
        raw = data[0]
        count = int(raw) if isinstance(raw, bytes) else 0
        log.info("Selected folder %r (%d messages)", folder, count)
        return count

    # -- retryable command execution --

    def execute(self, method_name: str, *args: object) -> tuple[str, list]:
        """Execute an IMAP command with retry and reconnect.

        Returns the (status, data) tuple from the IMAP command.
        Raises ConnectionError after exhausting retries.
        """
        last_exc: Exception | None = None

        for attempt in range(self.max_retries + 1):
            try:
                if self._imap is None:
                    self.reconnect()

                method = getattr(self.imap, method_name)
                status, data = method(*args)

                if status == "OK":
                    return status, data

                # Check for SERVERBUG — retriable
                resp_text = str(data)
                if "SERVERBUG" in resp_text:
                    log.warning(
                        "SERVERBUG on %s (attempt %d/%d), backing off",
                        method_name,
                        attempt + 1,
                        self.max_retries + 1,
                    )
                    self._backoff(attempt)
                    continue

                # Non-retriable IMAP error
                raise ConnectionError(
                    f"IMAP {method_name} failed: {status} {data}"
                )

            except (
                imaplib.IMAP4.abort,
                imaplib.IMAP4.error,
                socket.error,
                ssl.SSLError,
                OSError,
                ConnectionResetError,
                BrokenPipeError,
            ) as exc:
                last_exc = exc
                log.warning(
                    "Connection error on %s (attempt %d/%d): %s",
                    method_name,
                    attempt + 1,
                    self.max_retries + 1,
                    exc,
                )
                self._imap = None  # force reconnect
                self._backoff(attempt)

        raise ConnectionError(
            f"Failed after {self.max_retries + 1} attempts: {last_exc}"
        )

    def _backoff(self, attempt: int) -> None:
        delay = min(self.backoff_base ** (attempt + 1), self.backoff_max)
        log.debug("Sleeping %.1fs before retry", delay)
        time.sleep(delay)

    # -- context manager --

    def __enter__(self) -> IMAPConnection:
        self.connect()
        return self

    def __exit__(self, *exc: object) -> None:
        self.disconnect()