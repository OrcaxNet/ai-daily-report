import json

from ai_daily_report.assemble import render_site
from ai_daily_report.publish import publish_site
from ai_daily_report.state import StateStore
from ai_daily_report.models import Item, Report


def _report():
    items = [Item(
        item_id=f"id{i}", title_cn=f"标题{i}", summary_cn=f"摘要{i}", why_it_matters_cn=f"为什么{i}",
        tags=["AI"], category="模型进展", source_name="arXiv", source_url=f"https://example.com/{i}",
        source_published_at="2026-08-09T08:00:00+08:00", collected_at="2026-08-10T08:00:00+08:00",
        source_grade="A", fact_type="事实", score=80.0, dedup_key=f"k{i}", title_original="orig",
    ) for i in range(10)]
    return Report(
        report_date="2026-08-10", generated_at="2026-08-10T08:00:00+08:00",
        content_window_start="2026-08-09T06:30:00+08:00", content_window_end="2026-08-10T06:30:00+08:00",
        item_count=len(items), category_counts={"模型进展": 10}, corrections=[],
        data_cutoff="2026-08-10T06:30:00+08:00", ai_disclosure="x", items=items,
    )


def test_render_and_publish(tmp_path):
    state = StateStore(tmp_path / "repo")
    report = _report()
    staging = tmp_path / "staging"
    result = render_site(report, state, staging)
    assert (staging / "daily" / "2026-08-10.html").exists()
    assert (staging / "data" / "report-2026-08-10.json").exists()
    assert (staging / "index.html").exists()
    assert (staging / "archive.html").exists()

    site = tmp_path / "site"
    pub = publish_site(staging, site, "2026-08-10", state)
    assert (site / "daily" / "2026-08-10.html").exists()
    assert (site / "data" / "report-2026-08-10.json").exists()
    assert state.load()["last_published_date"] == "2026-08-10"
    assert "2026-08-10" in state.get_published_dates()


def test_publish_idempotent(tmp_path):
    state = StateStore(tmp_path / "repo")
    report = _report()
    staging = tmp_path / "staging"
    render_site(report, state, staging)
    site = tmp_path / "site"
    publish_site(staging, site, "2026-08-10", state)
    publish_site(staging, site, "2026-08-10", state)
    assert state.get_published_dates() == ["2026-08-10"]
