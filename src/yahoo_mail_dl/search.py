"""Date-windowed IMAP SEARCH with UID collection.

Yahoo/AOL servers cap SEARCH results at ~500 UIDs per command.
This module splits date ranges into narrow windows and collects
UIDs across all windows, deduplicating and sorting.
"""

from __future__ import annotations

import logging
import time
from datetime import date, timedelta
from typing import TYPE_CHECKING

from . import constants as C

if TYPE_CHECKING:
    from .connection import IMAPConnection

log = logging.getLogger(__name__)

# IMAP date format for SEARCH commands
_IMAP_DATE_FMT = "%d-%b-%Y"  # e.g. "01-Jan-2024"


def _imap_date(d: date) -> str:
    return d.strftime(_IMAP_DATE_FMT)


def date_windows(
    since: date, until: date, window_days: int = C.SEARCH_WINDOW_DAYS
) -> list[tuple[date, date]]:
    """Split a date range into windows of at most `window_days` days.

    Returns list of (window_start, window_end) inclusive pairs.
    """
    windows: list[tuple[date, date]] = []
    current = since
    while current < until:
        window_end = min(current + timedelta(days=window_days), until)
        windows.append((current, window_end))
        current = window_end
    return windows


def search_uids(
    conn: IMAPConnection,
    *,
    since: date | None = None,
    until: date | None = None,
    window_days: int = C.SEARCH_WINDOW_DAYS,
    search_delay: float = C.SEARCH_DELAY_SECONDS,
) -> list[bytes]:
    """Collect all UIDs in the selected folder matching the date range.

    Uses date windowing to stay under the MESSAGELIMIT=500 cap.
    Returns UIDs as a sorted list of byte strings.
    """
    if since is None and until is None:
        return _search_all_windowed(conn, window_days=window_days, delay=search_delay)

    # Default bounds
    if since is None:
        since = date(2000, 1, 1)
    if until is None:
        until = date.today()

    windows = date_windows(since, until, window_days)
    all_uids: set[bytes] = set()

    for i, (win_start, win_end) in enumerate(windows):
        criteria = f"(SINCE {_imap_date(win_start)} BEFORE {_imap_date(win_end)})"
        log.debug(
            "SEARCH window %d/%d: %s", i + 1, len(windows), criteria
        )

        status, data = conn.execute("uid", "SEARCH", None, criteria)
        uids = _parse_uid_response(data)
        log.debug("  -> %d UIDs", len(uids))
        all_uids.update(uids)

        # Rate limit between SEARCH commands
        if i < len(windows) - 1:
            time.sleep(search_delay)

    result = sorted(all_uids, key=lambda u: int(u))
    log.info("Total unique UIDs found: %d", len(result))
    return result


def _search_all_windowed(
    conn: IMAPConnection,
    *,
    window_days: int,
    delay: float,
) -> list[bytes]:
    """SEARCH ALL using year-by-year windowing as a fallback.

    When no date range is specified, we still need to window
    to avoid hitting the 500-UID cap on SEARCH ALL.
    """
    # Scan from 2000 to today in windows
    return search_uids(
        conn,
        since=date(2000, 1, 1),
        until=date.today() + timedelta(days=1),
        window_days=window_days,
        search_delay=delay,
    )


def _parse_uid_response(data: list) -> list[bytes]:
    """Parse the data portion of a UID SEARCH response.

    The server returns a list like [b'1 2 3 4 5'] or [None].
    """
    uids: list[bytes] = []
    for item in data:
        if item is None:
            continue
        raw = item if isinstance(item, bytes) else item.encode()
        for uid in raw.split():
            if uid.isdigit():
                uids.append(uid)
    return uids