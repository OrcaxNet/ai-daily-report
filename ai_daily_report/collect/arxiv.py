"""arXiv API 采集器（A 级一手）。"""

from __future__ import annotations

from typing import List

import feedparser

from ..util import parse_dt, http_get
from .base import Collector, CollectorError
from ..models import Candidate


class ArxivCollector(Collector):
    name = "arxiv"

    def collect(self) -> List[Candidate]:
        query = self.cfg.get("search_query", "cat:cs.AI OR cat:cs.CL OR cat:cs.LG")
        max_results = int(self.cfg.get("max_results", 60))
        url = (
            "http://export.arxiv.org/api/query?"
            f"search_query={query}&start=0&max_results={max_results}"
            "&sortBy=submittedDate&sortOrder=descending"
        )
        try:
            resp = http_get(url, timeout=self.timeout)
            parsed = feedparser.parse(resp.content)
        except Exception as e:  # noqa: BLE001
            raise CollectorError(f"arxiv fetch failed: {e}") from e

        out: List[Candidate] = []
        for e in parsed.entries:
            title = (e.get("title") or "").replace("\n", " ").strip()
            if not title:
                continue
            link = e.get("link", "").strip()
            summary = (e.get("summary") or "").replace("\n", " ").strip()
            published = ""
            if e.get("published_parsed"):
                import time as _time
                published = parse_dt(_time.strftime("%Y-%m-%dT%H:%M:%SZ", e["published_parsed"]))
                published = published.isoformat(timespec="seconds") if published else ""
            category = self._guess_category(title, summary)
            out.append(self._candidate(
                title=title, url=link, published_at=published, summary=summary,
                category_hint=category, dedup_hint=title, raw={"feed": "arxiv"},
            ))
        return out

    def _guess_category(self, title: str, summary: str) -> str:
        t = (title + " " + summary).lower()
        if any(k in t for k in ("agent", "tool use", "computer use", "multi-agent", "agentic", "mcp")):
            return "Agent 进展"
        if any(k in t for k in ("benchmark", "evaluation", "reasoning", "inference", "training", "model", "scaling", "pretrain")):
            return "模型进展"
        if any(k in t for k in ("theory", "mechanistic", "interpretab", "alignment", "safety", "mathematics", "optimization", "architecture")):
            return "基础理论"
        if any(k in t for k in ("application", "tool", "code", "medical", "biology", "education", "coding", "robot")):
            return "AI 应用"
        return ""
