"""采集器注册与编排（单源失败降级，不阻塞整体）。"""

from __future__ import annotations

import logging
from typing import List

from ..models import Candidate
from .base import Collector, CollectorError
from .rss import RssCollector
from .arxiv import ArxivCollector
from .hf import HfPapersCollector
from .github import GithubReleasesCollector
from .html_news import HtmlNewsCollector

log = logging.getLogger(__name__)

_COLLECTORS = {
    "rss": RssCollector,
    "arxiv": ArxivCollector,
    "hf_papers": HfPapersCollector,
    "github_releases": GithubReleasesCollector,
    "html_news": HtmlNewsCollector,
}


def get_collector(source_type: str) -> type:
    if source_type not in _COLLECTORS:
        raise CollectorError(f"unknown source type: {source_type}")
    return _COLLECTORS[source_type]


def collect_all(config: dict) -> tuple[List[Candidate], dict]:
    """执行所有启用来源采集。返回 (候选列表, 来源结果统计)。"""
    candidates: List[Candidate] = []
    stats = {}
    for name, cfg in config.get("sources", {}).items():
        try:
            cls = get_collector(cfg.get("type"))
            collector = cls({**cfg.get("params", {}), "display_name": cfg.get("display_name", name)},
                            cfg.get("grade", "A"), config.get("collection", {}))
            got = collector.collect()
            candidates.extend(got)
            stats[name] = {"ok": True, "count": len(got)}
            log.info("collect %s: %d candidates", name, len(got))
        except Exception as e:  # noqa: BLE001
            stats[name] = {"ok": False, "count": 0, "error": str(e)}
            log.warning("collect %s failed (degraded): %s", name, e)
    return candidates, stats
