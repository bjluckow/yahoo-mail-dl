"""Tests for the search module."""

from datetime import date

from yahoo_mail_dl.search import _parse_uid_response, date_windows


class TestDateWindows:
    def test_single_window(self):
        windows = date_windows(date(2024, 1, 1), date(2024, 1, 15), window_days=30)
        assert windows == [(date(2024, 1, 1), date(2024, 1, 15))]

    def test_multiple_windows(self):
        windows = date_windows(date(2024, 1, 1), date(2024, 3, 1), window_days=30)
        assert len(windows) == 2
        assert windows[0] == (date(2024, 1, 1), date(2024, 1, 31))
        assert windows[1] == (date(2024, 1, 31), date(2024, 3, 1))

    def test_exact_boundary(self):
        windows = date_windows(date(2024, 1, 1), date(2024, 1, 31), window_days=30)
        assert len(windows) == 1
        assert windows[0] == (date(2024, 1, 1), date(2024, 1, 31))

    def test_empty_range(self):
        windows = date_windows(date(2024, 1, 1), date(2024, 1, 1), window_days=30)
        assert windows == []

    def test_small_window(self):
        windows = date_windows(date(2024, 1, 1), date(2024, 2, 1), window_days=7)
        # 31 days / 7 = ~5 windows
        assert len(windows) >= 4
        # First window
        assert windows[0][0] == date(2024, 1, 1)
        # Last window ends at target
        assert windows[-1][1] == date(2024, 2, 1)


class TestParseUidResponse:
    def test_normal_response(self):
        data = [b"1 2 3 4 5"]
        assert _parse_uid_response(data) == [b"1", b"2", b"3", b"4", b"5"]

    def test_empty_response(self):
        assert _parse_uid_response([None]) == []
        assert _parse_uid_response([b""]) == []

    def test_multiple_chunks(self):
        data = [b"1 2 3", b"4 5 6"]
        assert _parse_uid_response(data) == [
            b"1", b"2", b"3", b"4", b"5", b"6"
        ]

    def test_non_numeric_filtered(self):
        data = [b"1 2 FLAGS 3"]
        result = _parse_uid_response(data)
        assert b"FLAGS" not in result
        assert result == [b"1", b"2", b"3"]