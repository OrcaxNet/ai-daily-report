from ai_daily_report.models import Candidate
from ai_daily_report.scoring import dedup_merge


def _cand(title, grade, url):
    return Candidate(
        source_name="src", source_url=url, source_published_at="2026-08-09T08:00:00+08:00",
        collected_at="2026-08-10T08:00:00+08:00", source_grade=grade, title_original=title,
        summary_original="summary", category_hint="模型进展", dedup_key_hint=title,
    )


def test_dedup_merges_same_event_keeps_a():
    a = _cand("Breaking Model Release News", "A", "https://a.example/1")
    b = _cand("Breaking Model Release News", "B", "https://b.example/1")
    out = dedup_merge([a, b])
    assert len(out) == 1
    assert out[0].source_grade == "A"
    assert out[0].source_url == "https://a.example/1"


def test_dedup_keeps_distinct():
    a = _cand("News One", "A", "https://a.example/1")
    b = _cand("News Two", "A", "https://a.example/2")
    out = dedup_merge([a, b])
    assert len(out) == 2
