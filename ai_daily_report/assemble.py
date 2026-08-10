"""组装步骤：渲染 HTML + JSON 元数据到 staging（PRD 步骤4）。"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .models import CATEGORIES, Report
from .state import StateStore


def _base_url() -> str:
    return "https://orcaxnet.github.io/ai-daily-report"


def render_site(report: Report, state_store: StateStore, staging_root: Path) -> dict:
    """渲染整个站点到 staging_root；返回 {date: {html, json}} 等产物。"""
    tpl_dir = Path(__file__).resolve().parent / "templates"
    static_dir = Path(__file__).resolve().parent / "static"
    env = Environment(
        loader=FileSystemLoader(str(tpl_dir)),
        autoescape=select_autoescape(["html"]),
    )

    staging_root = Path(staging_root)
    if staging_root.exists():
        shutil.rmtree(staging_root)
    daily_dir = staging_root / "daily"
    data_dir = staging_root / "data"
    assets_dir = staging_root / "assets"
    daily_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)
    assets_dir.mkdir(parents=True, exist_ok=True)

    published = sorted(state_store.get_published_dates())
    dates = published if report.report_date in published else sorted(published + [report.report_date])
    idx = dates.index(report.report_date)
    prev_date = dates[idx - 1] if idx > 0 else ""
    next_date = dates[idx + 1] if idx < len(dates) - 1 else ""

    items_by_category = {}
    for c in CATEGORIES:
        items_by_category[c] = [i for i in report.items if i.category == c]

    base_url = _base_url()
    ctx = {
        "report_date": report.report_date,
        "generated_at": report.generated_at,
        "content_window_start": report.content_window_start,
        "content_window_end": report.content_window_end,
        "data_cutoff": report.data_cutoff,
        "ai_disclosure": report.ai_disclosure,
        "items_by_category": items_by_category,
        "category_order": CATEGORIES,
        "insufficient_note": report.insufficient_note,
        "grace_note": report.grace_note,
        "prev_date": prev_date,
        "next_date": next_date,
        "base_url": base_url,
    }

    # 当日页
    daily_html = env.get_template("daily.html.j2").render(**ctx)
    (daily_dir / f"{report.report_date}.html").write_text(daily_html, encoding="utf-8")

    # JSON 数据文件
    (data_dir / f"report-{report.report_date}.json").write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    # 首页 / 归档 / 更正
    index_html = env.get_template("index.html.j2").render(
        base_url=base_url, ai_disclosure=report.ai_disclosure, latest_date=report.report_date)
    (staging_root / "index.html").write_text(index_html, encoding="utf-8")

    archive_html = env.get_template("archive.html.j2").render(
        base_url=base_url, ai_disclosure=report.ai_disclosure, dates=list(reversed(dates)))
    (staging_root / "archive.html").write_text(archive_html, encoding="utf-8")

    corrections = report.corrections or state_store.load().get("corrections", [])
    corr_html = env.get_template("corrections.html.j2").render(
        base_url=base_url, ai_disclosure=report.ai_disclosure, corrections=corrections)
    (staging_root / "corrections.html").write_text(corr_html, encoding="utf-8")

    shutil.copy2(static_dir / "style.css", assets_dir / "style.css")

    return {"staging_root": str(staging_root), "date": report.report_date}
