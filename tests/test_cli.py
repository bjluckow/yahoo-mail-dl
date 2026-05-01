"""Tests for CLI utilities."""

from yahoo_mail_dl.cli import _sanitize_filename


class TestSanitizeFilename:
    def test_strips_angle_brackets(self):
        assert _sanitize_filename("<abc@def.com>") == "abc@def.com"

    def test_replaces_unsafe_chars(self):
        result = _sanitize_filename('a/b\\c:d"e')
        assert "/" not in result
        assert "\\" not in result
        assert ":" not in result
        assert '"' not in result

    def test_truncates_long_names(self):
        long_name = "x" * 300
        assert len(_sanitize_filename(long_name)) == 200

    def test_empty_string(self):
        assert _sanitize_filename("") == "unknown"