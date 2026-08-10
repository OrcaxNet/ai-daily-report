"""校验步骤（PRD 步骤5）：字段完整、外链可达、无重复、移动端检查。校验失败不入库不发布。"""

from __future__ import annotations

import concurrent.futures as cf
import logging
from urllib.parse import urlparse

from .models import CATEGORIES, CORE_CATEGORIES, FACT_TYPES, Report
from .util import http_get

log = logging.getLogger(__name__)

REQUIRED_ITEM_FIELDS = [
    "item_id", "title_cn", "summary_cn", "why_it_matters_cn", "tags",
    "category", "source_name", "source_url", "source_published_at",
    "collected_at", "source_grade", "fact_type", "score", "dedup_key",
]


class ValidationError(Exception):
    pass


def validate_report(report: Report, check_links: bool = True, max_link_checks: int = 10,
                    link_workers: int = 4) -> None:
    errors = []

    # 报告级
    if not report.report_date or len(report.report_date) != 10:
        errors.append("report_date 缺失或格式错误")
    if not report.generated_at:
        errors.append("generated_at 缺失")
    if not report.content_window_start or not report.content_window_end:
        errors.append("内容窗口缺失")

    # 条目数量（PRD §2.1 P0-2：8-15 条或明确说明）
    n = len(report.items)
    if not (8 <= n <= 15):
        if not report.insufficient_note:
            errors.append(f"条目数 {n} 不在 8-15 范围且无不足说明")

    # 四核心栏目均被处理（有内容或明确「今日无重大更新」）
    for c in CORE_CATEGORIES:
        count = sum(1 for i in report.items if i.category == c)
        if count == 0 and c not in report.empty_categories:
            errors.append(f"核心栏目「{c}」无内容且未标记为空")

    # 条目字段完整性 + 合法性
    seen_ids, seen_links = set(), set()
    for i, item in enumerate(report.items):
        d = item.to_dict()
        for f in REQUIRED_ITEM_FIELDS:
            v = d.get(f)
            if v is None or (isinstance(v, str) and not v.strip()):
                errors.append(f"item[{i}] 字段 {f} 为空")
        if item.item_id in seen_ids:
            errors.append(f"item[{i}] item_id 重复: {item.item_id}")
        seen_ids.add(item.item_id)
        if item.source_url in seen_links:
            errors.append(f"item[{i}] source_url 重复: {item.source_url}")
        seen_links.add(item.source_url)
        if item.category not in CATEGORIES:
            errors.append(f"item[{i}] category 非法: {item.category}")
        if item.fact_type not in FACT_TYPES:
            errors.append(f"item[{i}] fact_type 非法: {item.fact_type}")
        if item.score < 60:
            errors.append(f"item[{i}] score {item.score} < 60")
        if not urlparse(item.source_url).scheme:
            errors.append(f"item[{i}] source_url 非法: {item.source_url}")

    # 外链可达性（抽样，HTTP 200）
    if check_links and report.items:
        targets = [i.source_url for i in report.items[:max_link_checks]]
        broken = _check_links(targets, link_workers)
        for url in broken:
            errors.append(f"外链不可达: {url}")

    if errors:
        raise ValidationError("；".join(errors[:30]))
    log.info("validate ok: %d items, %d categories", n, len({i.category for i in report.items}))


def _check_links(urls, workers: int = 4) -> list:
    def check(url):
        try:
            r = http_get(url, timeout=12)
            # GitHub/部分站点对 HEAD 可能 403，宽松处理：4xx 视为可达但记录
            return None if r.status_code < 400 else url
        except Exception:
            return url

    broken = []
    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        for res in ex.map(check, urls):
            if res:
                broken.append(res)
    return broken


def mobile_check(html: str) -> list:
    """基础移动端检查：无横向溢出风险（无固定大宽度内联样式 / 缺失 viewport）。"""
    issues = []
    if 'name="viewport"' not in html and "name='viewport'" not in html:
        issues.append("缺少 viewport meta")
    if "min-width:" in html:
        issues.append("检测到 min-width 内联样式，可能有横向溢出风险")
    return issues
