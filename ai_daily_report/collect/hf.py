"""Hugging Face 采集器：Papers API + 每日论文。"""

from __future__ import annotations

from typing import List

from ..util import parse_dt, http_get, now_shanghai
from ..models import Candidate
from .base import Collector, CollectorError


class HfPapersCollector(Collector):
    name = "hf_papers"

    def collect(self) -> List[Candidate]:
        max_results = int(self.cfg.get("max_results", 40))
        days = int(self.cfg.get("days", 3))
        url = f"https://huggingface.co/api/papers?limit={max_results}&days={days}"
        try:
            data = http_get(url, timeout=self.timeout).json()
        except Exception as e:  # noqa: BLE001
            raise CollectorError(f"hf_papers fetch failed: {e}") from e
        if not isinstance(data, list):
            raise CollectorError("hf_papers unexpected payload")

        out: List[Candidate] = []
        for p in data:
            title = (p.get("title") or "").strip()
            if not title:
                continue
            paper_id = p.get("paper_id") or p.get("id") or ""
            link = f"https://huggingface.co/papers/{paper_id}" if paper_id else ""
            summary = (p.get("summary") or p.get("abstract") or "").strip()
            published = parse_dt(p.get("publishedAt") or p.get("published_at") or "")
            published = published.isoformat(timespec="seconds") if published else ""
            out.append(self._candidate(
                title=title, url=link, published_at=published, summary=summary,
                category_hint="模型进展", dedup_hint=title, raw={"feed": "hf_papers"},
            ))
        return out
