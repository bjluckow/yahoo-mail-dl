# yahoo-mail-dl

Reliable bulk download of email from Yahoo Mail and AOL accounts via IMAP.

Yahoo and AOL IMAP servers enforce non-standard restrictions (500-message search caps, rate limiting, disconnects on large fetches) that cause standard IMAP clients to silently drop messages. This library handles all of that transparently.

## Install

```bash
pip install git+https://github.com/bjluckow/yahoo-mail-dl.git
```

## CLI Usage

```bash
# Download all mail from an AOL account
yahoo-mail-dl --username user@aol.com --password APP_PASSWORD

# Date range + specific folders + parallel download
yahoo-mail-dl \
    --username user@aol.com \
    --password APP_PASSWORD \
    --since 2020-01-01 \
    --until 2025-01-01 \
    --folders Inbox Sent \
    --workers 3 \
    -o my-mail-archive

# List folders without downloading
yahoo-mail-dl --username user@aol.com --password APP_PASSWORD --list-folders

# Yahoo Mail
yahoo-mail-dl \
    --host imap.mail.yahoo.com \
    --username user@yahoo.com \
    --password APP_PASSWORD
```

Password can also be set via `YAHOO_MAIL_DL_PASSWORD` environment variable.

Output is `.eml` files (RFC 2822) organized by folder:

```
yahoo-mail-dl-output/
  Inbox/
    <message-id>.eml
  Sent/
    <message-id>.eml
```

Runs are resumable — re-running the same command skips already-downloaded messages.

## Library Usage

```python
from datetime import date
from yahoo_mail_dl import YahooMailbox

with YahooMailbox(
    host="export.imap.aol.com",
    username="user@aol.com",
    password="APP_PASSWORD",
) as mb:
    for folder, msg in mb.fetch(since=date(2020, 1, 1)):
        print(folder, msg["Subject"])
```

### Resume support

Pass a `seen` set of Message-IDs to skip already-processed messages:

```python
seen = load_seen_ids_from_your_database()

with YahooMailbox(...) as mb:
    for folder, msg in mb.fetch(seen=seen):
        save_to_database(folder, msg)
        seen.add(msg["Message-ID"])
```

### Parallel folder download

```python
with YahooMailbox(...) as mb:
    for folder, msg in mb.fetch(workers=3):
        process(folder, msg)
```

### Tuning

All server-interaction parameters are configurable:

```python
mb = YahooMailbox(
    host="export.imap.aol.com",
    username="...",
    password="...",
    fetch_batch_size=50,     # messages per FETCH command
    search_window_days=30,   # days per SEARCH window
    search_delay=1.0,        # seconds between SEARCH commands
    fetch_delay=0.5,         # seconds between FETCH batches
)
```

## Requirements

- Python 3.10+
- No runtime dependencies (stdlib only)

## How it works

1. Connects via IMAP4-SSL and authenticates with an app password
2. For each folder, splits the date range into 30-day windows to stay under Yahoo's 500-result SEARCH cap
3. Fetches messages in small batches (default 50) to avoid server disconnects
4. Automatically reconnects and retries on SERVERBUG errors and dropped connections
5. Deduplicates by Message-ID so interrupted runs can resume cleanly

## License

MIT