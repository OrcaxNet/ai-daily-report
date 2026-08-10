from ai_daily_report.models import Candidate
from ai_daily_report.scoring import score_candidate, SCORE_THRESHOLD


def _cand(title, summary="", grade="A", source="arxiv"):
    return Candidate(
        source_name=source, source_url="https://example.com/x", source_published_at="2026-08-09T08:00:00+08:00",
        collected_at="2026-08-10T08:00:00+08:00", source_grade=grade, title_original=title,
        summary_original=summary, category_hint="模型进展", dedup_key_hint=title,
    )


def test_a_grade_high_score():
    c = _cand("OpenAI Announces GPT-5 with new API release", summary="The company launched a new model and API.")
    assert score_candidate(c) >= SCORE_THRESHOLD


def test_b_grade_lower_than_a():
    a = _cand("Major Model Launch", grade="A")
    b = _cand("Major Model Launch", grade="B")
    assert score_candidate(a) > score_candidate(b)


def test_score_bounded():
    c = _cand("release launch announce introducing new open source API agent coding tool app")
    assert 0 <= score_candidate(c) <= 100
