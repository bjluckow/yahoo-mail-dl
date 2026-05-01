"""Filter specification for client-side message filtering.

IMAP SEARCH on Yahoo/AOL is unreliable for address fields and still
subject to the 500-result cap, so address filtering is done client-side
after fetching the raw message.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.utils import getaddresses

log = logging.getLogger(__name__)

# Valid filter field names and which headers they map to
FILTER_FIELDS: dict[str, tuple[str, ...]] = {
    "sender": ("From",),
    "to": ("To",),
    "cc": ("Cc",),
    "bcc": ("Bcc",),
    "recipient": ("To", "Cc", "Bcc"),
    "any": ("From", "To", "Cc", "Bcc"),
}


@dataclass
class FilterSpec:
    """Client-side filters applied after message download.

    Each field holds a set of email addresses (lowercased).
    Within a field, addresses are OR'd — a message matches if *any*
    of the addresses appear in the relevant headers.
    Across fields, the match is AND'd — all populated fields must match.

    Fields:
        sender:    From header
        to:        To header
        cc:        Cc header
        bcc:       Bcc header
        recipient: To, Cc, or Bcc (any of them)
        any:       From, To, Cc, or Bcc (any of them)
    """

    sender: set[str] = field(default_factory=set)
    to: set[str] = field(default_factory=set)
    cc: set[str] = field(default_factory=set)
    bcc: set[str] = field(default_factory=set)
    recipient: set[str] = field(default_factory=set)
    any: set[str] = field(default_factory=set)

    @classmethod
    def from_filter_strings(cls, filters: list[str]) -> FilterSpec:
        """Parse CLI filter strings like 'sender:user@example.com'.

        Raises ValueError on invalid format or unknown field.
        """
        spec = cls()
        for f in filters:
            if ":" not in f:
                raise ValueError(
                    f"Invalid filter {f!r}: expected 'field:address' "
                    f"(fields: {', '.join(FILTER_FIELDS)})"
                )
            field_name, address = f.split(":", 1)
            field_name = field_name.strip().lower()
            address = address.strip().lower()

            if field_name not in FILTER_FIELDS:
                raise ValueError(
                    f"Unknown filter field {field_name!r}, "
                    f"expected one of: {', '.join(FILTER_FIELDS)}"
                )
            if not address:
                raise ValueError(f"Empty address in filter {f!r}")

            getattr(spec, field_name).add(address)

        return spec

    @property
    def is_empty(self) -> bool:
        return not any(
            [self.sender, self.to, self.cc, self.bcc, self.recipient, self.any]
        )

    def matches(self, msg: EmailMessage) -> bool:
        """Test whether a message passes all filters.

        Returns True if the message matches (or if no filters are set).
        """
        if self.is_empty:
            return True

        # Extract all addresses from relevant headers once
        extracted: dict[str, set[str]] = {}
        for header in ("From", "To", "Cc", "Bcc"):
            raw = msg.get_all(header, [])
            pairs = getaddresses(raw)
            extracted[header] = {addr.lower() for _, addr in pairs if addr}

        # Check each populated filter field (AND across fields)
        for field_name in ("sender", "to", "cc", "bcc", "recipient", "any"):
            addresses: set[str] = getattr(self, field_name)
            if not addresses:
                continue

            headers = FILTER_FIELDS[field_name]
            # Collect all addresses from the mapped headers
            msg_addresses: set[str] = set()
            for header in headers:
                msg_addresses |= extracted.get(header, set())

            # OR within field: any of the filter addresses must appear
            if not addresses & msg_addresses:
                return False

        return True