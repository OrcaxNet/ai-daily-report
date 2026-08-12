import requests
import pytest

from ai_daily_report.models import Item, Report
from ai_daily_report.validate import (
    validate_report, ValidationError, mobile_check, normalize_url, resolve_link,
)


def _item(i=0, category="模型进展", **overrides):
    base = dict(
        item_id=f"id{i}", title_cn=f"标题{i}", summary_cn=f"摘要{i}", why_it_matters_cn=f"为什么{i}",
        tags=["AI"], category=category, source_name="arXiv", source_url=f"https://example.com/{i}",
        source_published_at="2026-08-09T08:00:00+08:00", collected_at="2026-08-10T08:00:00+08:00",
        source_grade="A", fact_type="事实", score=80.0, dedup_key=f"k{i}", title_original="orig",
    )
    base.update(overrides)
    return Item(**base)


_CATS = ["基础理论", "模型进展", "Agent 进展", "AI 应用"]


def _report(items, count=10):
    # 默认构造覆盖 4 个核心栏目的 10 条
    if not items:
        items = [_item(i, category=_CATS[i % 4]) for i in range(count)]
    return Report(
        report_date="2026-08-10", generated_at="2026-08-10T08:00:00+08:00",
        content_window_start="2026-08-09T06:30:00+08:00", content_window_end="2026-08-10T06:30:00+08:00",
        item_count=len(items), category_counts={}, corrections=[], data_cutoff="2026-08-10T06:30:00+08:00",
        ai_disclosure="x", items=items, empty_categories=[],
    )


def test_valid_report_passes():
    items = [_item(i, category=_CATS[i % 4]) for i in range(10)]
    validate_report(_report(items), check_links=False)


def test_missing_field_fails():
    items = [_item(0, category=_CATS[0], title_cn="")] + [_item(i, category=_CATS[i % 4]) for i in range(1, 10)]
    with pytest.raises(ValidationError):
        validate_report(_report(items), check_links=False)


def test_bad_category_fails():
    items = [_item(0, category="不存在")] + [_item(i, category=_CATS[i % 4]) for i in range(1, 10)]
    with pytest.raises(ValidationError):
        validate_report(_report(items), check_links=False)


def test_low_score_fails():
    items = [_item(0, category=_CATS[0], score=40.0)] + [_item(i, category=_CATS[i % 4]) for i in range(1, 10)]
    with pytest.raises(ValidationError):
        validate_report(_report(items), check_links=False)


def test_core_category_missing_fails_unless_empty():
    items = [_item(i, category="AI 应用") for i in range(10)]
    with pytest.raises(ValidationError):
        validate_report(_report(items), check_links=False)
    r = _report(items)
    r.empty_categories = ["基础理论", "模型进展", "Agent 进展"]
    validate_report(r, check_links=False)


def test_item_count_out_of_range_requires_note():
    items = [_item(i, category=_CATS[i % 4]) for i in range(4)]
    with pytest.raises(ValidationError):
        validate_report(_report(items), check_links=False)
    r = _report(items)
    r.insufficient_note = "今日仅有 4 条达标内容"
    validate_report(r, check_links=False)


def test_mobile_check():
    assert mobile_check('<html><head><meta name="viewport" content="width=device-width"></head></html>') == []
    assert mobile_check("<html><head></head></html>") != []


class _Response:
    def __init__(self, status_code, url):
        self.status_code = status_code
        self.url = url


class _Session:
    def __init__(self, effects):
        self.effects = iter(effects)
        self.get_calls = 0
        self.head_calls = 0

    def get(self, *args, **kwargs):
        self.get_calls += 1
        effect = next(self.effects)
        if isinstance(effect, Exception):
            raise effect
        return effect

    def head(self, *args, **kwargs):
        self.head_calls += 1
        return _Response(405, args[0])


def test_resolve_link_follows_redirect_and_stores_canonical_url():
    session = _Session([_Response(200, "https://openai.com/index/example/")])
    result = resolve_link("https://openai.com/index/example", session=session)
    assert result.usable
    assert result.canonical_url == "https://openai.com/index/example/"


def test_resolve_link_uses_get_not_head_false_negative():
    session = _Session([_Response(200, "https://example.com/article/")])
    result = resolve_link("https://example.com/article", session=session)
    assert result.usable
    assert session.get_calls == 1
    assert session.head_calls == 0


def test_resolve_link_retries_transient_errors_with_backoff():
    session = _Session([
        _Response(429, "https://example.com/"),
        requests.Timeout("timed out"),
        _Response(200, "https://example.com/final/"),
    ])
    sleeps = []
    result = resolve_link("https://example.com", session=session, retries=2,
                          backoff=0.1, sleep_fn=sleeps.append)
    assert result.usable
    assert result.canonical_url == "https://example.com/final/"
    assert sleeps == [0.1, 0.2]


def test_resolve_link_confirms_404_as_hard_failure():
    session = _Session([_Response(404, "https://example.com/missing/")])
    result = resolve_link("https://example.com/missing", session=session)
    assert not result.usable
    assert result.reason == "hard_failure"


def test_openai_soft_403_uses_known_canonical_trailing_slash():
    session = _Session([_Response(403, "https://openai.com/index/example")])
    result = resolve_link("https://openai.com/index/example", session=session)
    assert result.usable
    assert result.reason == "soft_http_failure"
    assert result.canonical_url == "https://openai.com/index/example/"


def test_normalize_url_strips_fragment_and_adds_root_slash():
    assert normalize_url("HTTPS://EXAMPLE.COM#part") == "https://example.com/"
