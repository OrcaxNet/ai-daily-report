from ai_daily_report.cli import _replace_unreachable
from ai_daily_report.models import Candidate
from ai_daily_report.validate import LinkResult, normalize_url


def _candidate(i, category="模型进展"):
    return Candidate(
        source_name="official", source_url=f"https://example.com/{i}",
        source_published_at="2026-08-11T01:00:00+08:00",
        collected_at="2026-08-12T08:00:00+08:00", source_grade="A",
        title_original=f"New AI model release {i}",
        summary_original="New model API release available to developers",
        category_hint=category, dedup_key_hint=f"key-{i}",
    )


def _result(url, usable=True, reason="ok", canonical=None):
    return LinkResult(normalize_url(url), canonical or normalize_url(url), usable, reason,
                      200 if usable else 404)


def test_hard_failure_is_replaced_from_same_category_first():
    selected_candidates = [
        _candidate(0, "基础理论"), _candidate(1, "模型进展"),
        _candidate(2, "Agent 进展"), _candidate(3, "AI 应用"),
        *[_candidate(i, "模型进展") for i in range(4, 8)],
    ]
    alternate_same = _candidate(8, "基础理论")
    alternate_other = _candidate(9, "AI 应用")
    selected = [(candidate, 80.0) for candidate in selected_candidates]

    def resolver(url):
        if url.endswith("/0"):
            return _result(url, False, "hard_failure")
        return _result(url, canonical=normalize_url(url) + "/")

    output = _replace_unreachable(
        selected, selected_candidates + [alternate_other, alternate_same], resolver=resolver,
    )
    urls = [candidate.source_url for candidate, _ in output]
    assert alternate_same.source_url in urls
    assert alternate_other.source_url not in urls
    assert len(output) == 8


def test_replacement_exhaustion_below_hard_minimum_fails():
    candidates = [_candidate(i, ["基础理论", "模型进展", "Agent 进展", "AI 应用"][i % 4])
                  for i in range(8)]

    def resolver(url):
        return _result(url, not url.endswith("/0"), "hard_failure")

    try:
        _replace_unreachable([(candidate, 80.0) for candidate in candidates], candidates,
                             resolver=resolver)
    except RuntimeError as exc:
        assert "低于硬门槛" in str(exc)
    else:
        raise AssertionError("expected replacement exhaustion to fail")
