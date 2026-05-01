"""Default constants for Yahoo/AOL IMAP bulk download.

These are conservative defaults based on observed server behavior.
All are overridable via YahooMailbox constructor kwargs.
"""

# -- Known IMAP hosts --
HOSTS = {
    "yahoo": "imap.mail.yahoo.com",
    "aol": "export.imap.aol.com",
    "aol_standard": "imap.aol.com",
}

IMAP_PORT = 993

# -- Server-side limits --
# Yahoo/AOL cap SEARCH results at 500 UIDs per command.
# Keeping SEARCH windows narrow enough to stay under this is critical.
SEARCH_WINDOW_DAYS = 30

# -- Fetch batching --
# Fetching too many messages in one FETCH command causes the server to
# log out and drop the connection.  50 is safe; 100 is borderline.
FETCH_BATCH_SIZE = 50

# -- Rate limiting --
# Seconds to sleep between SEARCH commands to avoid SERVERBUG errors.
SEARCH_DELAY_SECONDS = 1.0

# Seconds to sleep between FETCH batches.
FETCH_DELAY_SECONDS = 0.5

# -- Retry / reconnect --
MAX_RETRIES = 5
RETRY_BACKOFF_BASE = 2.0  # exponential: 2, 4, 8, 16, 32 seconds
RETRY_BACKOFF_MAX = 60.0

# -- Connection --
IMAP_TIMEOUT_SECONDS = 60

# -- Threading --
DEFAULT_WORKERS = 1
MAX_WORKERS = 5  # Yahoo likely rejects beyond ~5 concurrent connections