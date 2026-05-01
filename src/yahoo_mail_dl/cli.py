"""CLI for yahoo-mail-dl: bulk download Yahoo/AOL email to .eml files."""

from __future__ import annotations

import argparse
import logging
import os
import re
import sys
from datetime import date
from pathlib import Path

from . import constants as C
from .mailbox import YahooMailbox

log = logging.getLogger(__name__)


def _sanitize_filename(name: str) -> str:
    """Make a Message-ID safe for use as a filename."""
    # Strip angle brackets, replace filesystem-unsafe chars
    name = name.strip("<>")
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
    # Truncate to avoid path length issues
    return name[:200] if name else "unknown"


def _parse_date(s: str) -> date:
    """Parse YYYY-MM-DD date string."""
    try:
        return date.fromisoformat(s)
    except ValueError:
        raise argparse.ArgumentTypeError(f"Invalid date: {s!r} (expected YYYY-MM-DD)")


def _build_seen_set(output_dir: Path) -> set[str]:
    """Scan existing .eml files to build the set of already-downloaded Message-IDs.

    Filenames are sanitized Message-IDs, so we reverse the mapping.
    We also peek at the file header to extract the real Message-ID.
    """
    seen: set[str] = set()
    if not output_dir.exists():
        return seen

    for eml_path in output_dir.rglob("*.eml"):
        # Fast path: read just the first few KB to find Message-ID header
        try:
            head = eml_path.read_bytes()[:8192]
            for line in head.split(b"\n"):
                if line.lower().startswith(b"message-id:"):
                    mid = line.split(b":", 1)[1].strip().decode(errors="replace")
                    seen.add(mid)
                    break
        except OSError:
            continue

    return seen


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="yahoo-mail-dl",
        description="Bulk download email from Yahoo Mail / AOL via IMAP.",
    )
    parser.add_argument(
        "--provider",
        choices=list(C.HOSTS.keys()),
        default=None,
        help="Mail provider shortcut: " + ", ".join(
            f"{k} ({v})" for k, v in C.HOSTS.items()
        ),
    )
    parser.add_argument(
        "--host",
        default=None,
        help="IMAP host (overrides --provider)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=C.IMAP_PORT,
        help=f"IMAP port (default: {C.IMAP_PORT})",
    )
    parser.add_argument("--username", required=True, help="Email address / username")
    parser.add_argument(
        "--password",
        default=None,
        help="App password (or set YAHOO_MAIL_DL_PASSWORD env var)",
    )
    parser.add_argument(
        "--since",
        type=_parse_date,
        default=None,
        help="Fetch messages on or after this date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--until",
        type=_parse_date,
        default=None,
        help="Fetch messages before this date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--folders",
        default=None,
        help="Comma-separated folder names to fetch (default: all). "
        'Quote names with spaces: --folders "Sent Items,Inbox,Drafts"',
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("yahoo-mail-dl-output"),
        help="Output directory (default: yahoo-mail-dl-output)",
    )
    parser.add_argument(
        "-w",
        "--workers",
        type=int,
        default=C.DEFAULT_WORKERS,
        help=f"Concurrent folder downloads (default: {C.DEFAULT_WORKERS}, max: {C.MAX_WORKERS})",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=C.FETCH_BATCH_SIZE,
        help=f"Messages per FETCH command (default: {C.FETCH_BATCH_SIZE})",
    )
    parser.add_argument(
        "--window-days",
        type=int,
        default=C.SEARCH_WINDOW_DAYS,
        help=f"Days per SEARCH window (default: {C.SEARCH_WINDOW_DAYS})",
    )
    parser.add_argument(
        "--list-folders",
        action="store_true",
        help="List folders and exit (do not download)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="Increase verbosity (-v info, -vv debug)",
    )

    args = parser.parse_args(argv)

    # -- logging --
    level = {0: logging.WARNING, 1: logging.INFO}.get(args.verbose, logging.DEBUG)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    # -- password --
    password = args.password or os.environ.get("YAHOO_MAIL_DL_PASSWORD")
    if not password:
        print(
            "Error: supply --password or set YAHOO_MAIL_DL_PASSWORD env var",
            file=sys.stderr,
        )
        return 1

    # -- connect --
    with YahooMailbox(
        host=args.host,
        username=args.username,
        password=password,
        port=args.port,
        fetch_batch_size=args.batch_size,
        search_window_days=args.window_days,
    ) as mb:
        # -- list-folders mode --
        if args.list_folders:
            for folder in mb.list_folders():
                print(folder)
            return 0

        # -- download mode --
        output_dir: Path = args.output
        seen = _build_seen_set(output_dir)
        if seen:
            log.info("Resuming: %d messages already downloaded", len(seen))

        count = 0
        try:
            for folder, msg in mb.fetch(
                since=args.since,
                until=args.until,
                folders=[f.strip() for f in args.folders.split(",")]
                if args.folders
                else None,
                seen=seen,
                workers=args.workers,
            ):
                folder_dir = output_dir / _sanitize_filename(folder)
                folder_dir.mkdir(parents=True, exist_ok=True)

                message_id = msg.get("Message-ID", f"no-id-{count}")
                filename = _sanitize_filename(message_id) + ".eml"
                filepath = folder_dir / filename

                if filepath.exists():
                    continue

                filepath.write_bytes(msg.as_bytes())
                count += 1

                if count % 100 == 0:
                    log.info("Downloaded %d messages so far...", count)

        except KeyboardInterrupt:
            log.info("Interrupted after %d messages", count)

    print(f"Downloaded {count} messages to {output_dir.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())