"""校验步骤（PRD 步骤5）：字段完整、外链可达、无重复、移动端检查。校验失败不入库不发布。"""

from __future__ import annotations

import concurrent.futures as cf
import logging
import time
from dataclasses import dataclass
from urllib.parse import urlparse, urlunparse

import requests

from .models import CATEGORIES, CORE_CATEGORIES, FACT_TYPES, Report
log = logging.getLogger(__name__)

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


@dataclass(frozen=True)
class LinkResult:
    original_url: str
    canonical_url: str
    usable: bool
    reason: str
    status_code: int | None = None


def normalize_url(url: str) -> str:
    """规范化 URL，避免把缺少根路径斜杠等价地址视为不同链接。"""
    parsed = urlparse(url.strip())
    path = parsed.path or "/"
    return urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), path,
                       parsed.params, parsed.query, ""))


def resolve_link(url: str, retries: int = 2, backoff: float = 0.5,
                 session=None, sleep_fn=time.sleep, timeout: int = 15) -> LinkResult:
    """用浏览器式 GET 跟随重定向并分类结果；只有确认的硬失效才立即判死链。

    429、5xx 和网络错误按退避重试，耗尽后视为本次最终不可达；单次
    403/405 不作为死链，避免反爬/HEAD 策略造成假阴性。
    """
    original = normalize_url(url)
    client = session or requests.Session()
    last_status = None
    last_reason = ""

    request_url = original
    for attempt in range(retries + 1):
        try:
            response = client.get(
                request_url, headers=BROWSER_HEADERS, timeout=timeout,
                allow_redirects=True,
            )
            last_status = response.status_code
            canonical = normalize_url(response.url or original)
            if response.status_code < 400:
                return LinkResult(original, canonical, True, "ok", response.status_code)
            if response.status_code in (404, 410):
                return LinkResult(original, canonical, False, "hard_failure", response.status_code)
            if response.status_code in (429,) or response.status_code >= 500:
                last_reason = "transient_failure"
            else:
                # 403/405 等可能来自反爬或方法策略；产品决策要求不能据此判死链。
                parsed = urlparse(canonical)
                if (parsed.netloc == "openai.com" and parsed.path.startswith("/index/")
                        and not parsed.path.endswith("/")):
                    canonical = urlunparse(parsed._replace(path=parsed.path + "/"))
                return LinkResult(original, canonical, True, "soft_http_failure", response.status_code)
        except requests.RequestException as exc:
            last_reason = f"transient_failure: {exc.__class__.__name__}"

        if attempt < retries:
            sleep_fn(backoff * (2 ** attempt))

    return LinkResult(original, original, False, last_reason or "transient_failure", last_status)

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
        results = _check_links(targets, link_workers)
        by_original = {result.original_url: result for result in results}
        for item in report.items[:max_link_checks]:
            result = by_original[normalize_url(item.source_url)]
            if result.usable:
                item.source_url = result.canonical_url
            else:
                errors.append(f"外链不可达({result.reason}): {item.source_url}")

    if errors:
        raise ValidationError("；".join(errors[:30]))
    log.info("validate ok: %d items, %d categories", n, len({i.category for i in report.items}))


def _check_links(urls, workers: int = 4) -> list[LinkResult]:
    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        return list(ex.map(resolve_link, urls))


def mobile_check(html: str) -> list:
    """基础移动端检查：无横向溢出风险（无固定大宽度内联样式 / 缺失 viewport）。"""
    issues = []
    if 'name="viewport"' not in html and "name='viewport'" not in html:
        issues.append("缺少 viewport meta")
    if "min-width:" in html:
        issues.append("检测到 min-width 内联样式，可能有横向溢出风险")
    return issues
