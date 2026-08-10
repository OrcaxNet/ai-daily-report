"""通用 RSS/Atom 采集器（官方博客）。"""

from __future__ import annotations

from typing import List

import feedparser

from ..util import parse_dt, http_get
from .base import Collector, CollectorError
from ..models import Candidate


class RssCollector(Collector):
    name = "rss"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.feed_url = self.cfg.get("feed_url", "")

    def collect(self) -> List[Candidate]:
        if not self.feed_url:
            raise CollectorError("RSS collector missing feed_url")
        try:
            resp = http_get(self.feed_url, timeout=self.timeout)
            parsed = feedparser.parse(resp.content)
        except Exception as e:  # noqa: BLE001
            raise CollectorError(f"{self.name} fetch failed: {e}") from e
        if parsed.get("bozo") and not parsed.entries:
            raise CollectorError(f"{self.name} parse failed: {parsed.get('bozo_exception')}")

        out: List[Candidate] = []
        for e in parsed.entries[: int(self.cfg.get("max_items", 40))]:
            title = e.get("title", "").strip()
            if not title:
                continue
            link = e.get("link", "").strip()
            summary = (e.get("summary") or e.get("description") or "").strip()
            dt = None
            for key in ("published_parsed", "updated_parsed"):
                if e.get(key):
                    try:
                        import time as _time
                        dt = parse_dt(_time.strftime("%Y-%m-%dT%H:%M:%SZ", e[key]))
                        break
                    except Exception:
                        continue
            if dt is None:
                dt = parse_dt(e.get("published") or e.get("updated") or "")
            published = dt.isoformat(timespec="seconds") if dt else ""
            category = self._guess_category(title, summary)
            out.append(self._candidate(
                title=title, url=link, published_at=published,
                summary=summary, category_hint=category, dedup_hint=title, raw={"feed": self.name},
            ))
        return out

    def _guess_category(self, title: str, summary: str) -> str:
        t = (title + " " + summary).lower()
        if any(k in t for k in ("agent", "tool use", "computer use", "multi-agent", "mcp")):
            return "Agent 进展"
        if any(k in t for k in ("model", "llm", "foundation model", "gpt", "claude", "gemini", "llama", "qwen", "deepseek", "open weights")):
            return "模型进展"
        if any(k in t for k in ("api", "sdk", "app", "product", "feature", "launch", "release", "studio", "platform")):
            return "AI 应用"
        if any(k in t for k in ("research", "paper", "theory", "scaling", "mechanistic", "interpret", "alignment", "safety")):
            return "基础理论"
        return ""
