from ai_daily_report.util import window_for, parse_dt, normalize_title, make_dedup_key


def test_window_for_24h():
    ws, we = window_for("2026-08-10")
    assert ws == "2026-08-09T06:30:00+08:00"
    assert we == "2026-08-10T06:30:00+08:00"


def test_parse_dt_formats():
    assert parse_dt("2026-08-10T10:28:13Z") is not None
    assert parse_dt("2026-08-10") is not None
    assert parse_dt("Jul 24, 2026") is not None
    assert parse_dt("garbage") is None


def test_normalize_title():
    assert normalize_title("Hello, World!") == "hello world"
    assert normalize_title("  A   B  ") == "a b"


def test_dedup_key_stable():
    assert make_dedup_key("Hello World") == make_dedup_key("hello world")
    assert make_dedup_key("A") != make_dedup_key("B")
