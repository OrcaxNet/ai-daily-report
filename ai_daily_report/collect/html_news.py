"""官方新闻列表页 HTML 采集器（无 RSS 的官方源：Anthropic / Mistral 等）。"""

from __future__ import annotations

import re
from typing import List

from bs4 import BeautifulSoup

from ..util import parse_dt, http_get
from ..models import Candidate
from .base import Collector, CollectorError

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def _parse_iso_date(s: str):
    """解析 'Jul 24, 2026' / '2026-07-24' 等，返回 ISO 日期或 None。"""
    s = s.strip()
    m = re.match(r"([A-Za-z]{3,9})\.?\s+(\d{1,2}),\s+(\d{4})", s)
    if m:
        mon = _MONTHS.get(m.group(1)[:3].lower())
        if mon:
            return f"{m.group(3)}-{mon:02d}-{int(m.group(2)):02d}"
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return s[:10]
    return None


class HtmlNewsCollector(Collector):
    name = "html_news"

    def collect(self) -> List[Candidate]:
        list_url = self.cfg.get("list_url", "")
        prefix = self.cfg.get("article_url_prefix", "")
        max_articles = int(self.cfg.get("max_articles", 15))
        if not list_url:
            raise CollectorError("html_news missing list_url")
        try:
            html = http_get(list_url, timeout=self.timeout).text
        except Exception as e:  # noqa: BLE001
            raise CollectorError(f"{self.name} list fetch failed: {e}") from e

        soup = BeautifulSoup(html, "html.parser")
        items = self._extract(soup)
        if not items:
            raise CollectorError(f"{self.name} no articles extracted from {list_url}")

        out: List[Candidate] = []
        for title, url, date_iso in items[:max_articles]:
            if not title or not url:
                continue
            full_url = url if url.startswith("http") else (prefix.rstrip("/") + url)
            published = ""
            if date_iso:
                dt = parse_dt(date_iso)
                published = dt.isoformat(timespec="seconds") if dt else date_iso + "T00:00:00+08:00"
            summary = self._article_summary(full_url)
            out.append(self._candidate(
                title=title, url=full_url, published_at=published, summary=summary,
                category_hint="模型进展", dedup_hint=title, raw={"feed": self.name},
            ))
        return out

    def _extract(self, soup: BeautifulSoup):
        """从列表页提取 (title, href, date_iso) 列表。"""
        out = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "/news/" not in href and "/blog/" not in href:
                continue
            title = a.get_text(" ", strip=True)
            if len(title) < 8:
                continue
            # 在 anchor 附近找日期
            date_iso = self._nearby_date(a)
            out.append((title, href, date_iso))
        # 去重（按 href）
        seen, uniq = set(), []
        for t, h, d in out:
            if h in seen:
                continue
            seen.add(h)
            uniq.append((t, h, d))
        return uniq

    def _nearby_date(self, a) -> str:
        container = a
        for _ in range(4):
            if container is None:
                break
            container = container.parent
            if container is None:
                break
            text = container.get_text(" ", strip=True)
            m = re.search(r"([A-Za-z]{3,9}\.?\s+\d{1,2},\s+\d{4}|\d{4}-\d{2}-\d{2})", text)
            if m:
                return _parse_iso_date(m.group(1)) or ""
            for t in container.find_all("time"):
                iso = _parse_iso_date(t.get_text(" ", strip=True))
                if iso:
                    return iso
        # 列表页全文找时间元素
        for t in a.find_all_previous("time", limit=6):
            iso = _parse_iso_date(t.get_text(" ", strip=True))
            if iso:
                return iso
        return ""

    def _article_summary(self, url: str, max_len: int = 600) -> str:
        try:
            html = http_get(url, timeout=self.timeout).text
        except Exception:
            return ""
        soup = BeautifulSoup(html, "html.parser")
        og = soup.find("meta", attrs={"property": "og:description"})
        if og and og.get("content"):
            return og["content"].strip()[:max_len]
        desc = soup.find("meta", attrs={"name": "description"})
        if desc and desc.get("content"):
            return desc["content"].strip()[:max_len]
        return ""
