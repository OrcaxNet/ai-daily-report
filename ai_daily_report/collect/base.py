"""采集器基类与候选条目。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List

from ..models import Candidate
from ..util import now_shanghai, fmt_iso


class CollectorError(Exception):
    pass


class Collector(ABC):
    """单个来源采集器。子类实现 collect()，失败抛 CollectorError（由编排降级）。"""

    name = "base"

    def __init__(self, cfg: dict, grade: str, collection_cfg: dict):
        self.cfg = cfg or {}
        self.grade = grade
        self.collection_cfg = collection_cfg or {}

    @property
    def timeout(self) -> int:
        return int(self.collection_cfg.get("http_timeout", 15))

    def _candidate(self, title: str, url: str, published_at: str, summary: str = "",
                   category_hint: str = "", dedup_hint: str = "", raw: dict = None) -> Candidate:
        return Candidate(
            source_name=self.cfg.get("display_name", self.name),
            source_url=url,
            source_published_at=published_at,
            collected_at=fmt_iso(now_shanghai()),
            source_grade=self.grade,
            title_original=title.strip(),
            summary_original=(summary or "").strip(),
            category_hint=category_hint,
            dedup_key_hint=dedup_hint or title,
            raw=raw or {},
        )

    @abstractmethod
    def collect(self) -> List[Candidate]:
        ...
