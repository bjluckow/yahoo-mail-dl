"""Tests for the filters module."""

import email
import email.message
import email.policy

import pytest

from yahoo_mail_dl.filters import FilterSpec


def _make_msg(
    from_: str = "alice@example.com",
    to: str = "bob@example.com",
    cc: str = "",
    bcc: str = "",
) -> email.message.EmailMessage:
    msg = email.message.EmailMessage()
    msg["From"] = from_
    msg["To"] = to
    if cc:
        msg["Cc"] = cc
    if bcc:
        msg["Bcc"] = bcc
    msg["Subject"] = "test"
    msg["Message-ID"] = "<test@example.com>"
    return msg


class TestFilterSpecParsing:
    def test_basic(self):
        spec = FilterSpec.from_filter_strings(["sender:alice@example.com"])
        assert "alice@example.com" in spec.sender

    def test_multiple_same_field(self):
        spec = FilterSpec.from_filter_strings([
            "sender:alice@example.com",
            "sender:bob@example.com",
        ])
        assert spec.sender == {"alice@example.com", "bob@example.com"}

    def test_multiple_fields(self):
        spec = FilterSpec.from_filter_strings([
            "sender:alice@example.com",
            "to:bob@example.com",
        ])
        assert spec.sender == {"alice@example.com"}
        assert spec.to == {"bob@example.com"}

    def test_case_insensitive(self):
        spec = FilterSpec.from_filter_strings(["Sender:Alice@Example.COM"])
        assert "alice@example.com" in spec.sender

    def test_invalid_no_colon(self):
        with pytest.raises(ValueError, match="expected 'field:address'"):
            FilterSpec.from_filter_strings(["alice@example.com"])

    def test_invalid_unknown_field(self):
        with pytest.raises(ValueError, match="Unknown filter field"):
            FilterSpec.from_filter_strings(["subject:hello"])

    def test_invalid_empty_address(self):
        with pytest.raises(ValueError, match="Empty address"):
            FilterSpec.from_filter_strings(["sender:"])

    def test_empty_list(self):
        spec = FilterSpec.from_filter_strings([])
        assert spec.is_empty


class TestFilterSpecMatching:
    def test_empty_filter_matches_all(self):
        spec = FilterSpec()
        assert spec.matches(_make_msg())

    def test_sender_match(self):
        spec = FilterSpec(sender={"alice@example.com"})
        assert spec.matches(_make_msg(from_="alice@example.com"))
        assert not spec.matches(_make_msg(from_="eve@example.com"))

    def test_sender_or(self):
        spec = FilterSpec(sender={"alice@example.com", "bob@example.com"})
        assert spec.matches(_make_msg(from_="alice@example.com"))
        assert spec.matches(_make_msg(from_="bob@example.com"))
        assert not spec.matches(_make_msg(from_="eve@example.com"))

    def test_to_match(self):
        spec = FilterSpec(to={"bob@example.com"})
        assert spec.matches(_make_msg(to="bob@example.com"))
        assert not spec.matches(_make_msg(to="eve@example.com"))

    def test_cc_match(self):
        spec = FilterSpec(cc={"carol@example.com"})
        assert spec.matches(_make_msg(cc="carol@example.com"))
        assert not spec.matches(_make_msg(cc="eve@example.com"))
        assert not spec.matches(_make_msg())  # no Cc header

    def test_recipient_matches_to_cc_bcc(self):
        spec = FilterSpec(recipient={"target@example.com"})
        assert spec.matches(_make_msg(to="target@example.com"))
        assert spec.matches(_make_msg(cc="target@example.com"))
        assert spec.matches(_make_msg(bcc="target@example.com"))
        assert not spec.matches(_make_msg(from_="target@example.com"))

    def test_any_matches_all_headers(self):
        spec = FilterSpec(any={"target@example.com"})
        assert spec.matches(_make_msg(from_="target@example.com"))
        assert spec.matches(_make_msg(to="target@example.com"))
        assert spec.matches(_make_msg(cc="target@example.com"))
        assert spec.matches(_make_msg(bcc="target@example.com"))
        assert not spec.matches(_make_msg())

    def test_and_across_fields(self):
        spec = FilterSpec(
            sender={"alice@example.com"},
            to={"bob@example.com"},
        )
        # Both match
        assert spec.matches(_make_msg(from_="alice@example.com", to="bob@example.com"))
        # Only sender matches
        assert not spec.matches(_make_msg(from_="alice@example.com", to="eve@example.com"))
        # Only recipient matches
        assert not spec.matches(_make_msg(from_="eve@example.com", to="bob@example.com"))

    def test_case_insensitive_matching(self):
        spec = FilterSpec(sender={"alice@example.com"})
        assert spec.matches(_make_msg(from_="Alice@Example.COM"))