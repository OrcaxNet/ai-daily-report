"""100 分制打分 + 同事件跨源去重合并（PRD §3.3）。"""

from __future__ import annotations

import re
from datetime import datetime
from typing import List, Dict

from .models import Candidate
from .util import make_dedup_key, parse_dt, TZ_SHANGHAI

# 分数权重：影响范围30 / 新颖性20 / 可验证性20 / 行动价值20 / 中文用户相关性10
W_IMPACT = 30.0
W_NOVELTY = 20.0
W_VERIFIABLE = 20.0
W_ACTION = 20.0
W_CN = 10.0
SCORE_THRESHOLD = 60.0


_STRONG = [
    "release", "launch", "announce", "introducing", "new", "开源", "发布", "上线",
    "正式", "突破", "超越", "state-of-the-art", "sota", "benchmark", "api",
    "first", "open weights", "open-source", "open source",
]
_RESEARCH = [
    "agent", "model", "training", "framework", "efficient", "novel", "scaling",
    "reasoning", "benchmark", "evaluation", "diffusion", "llm", "language model",
    "vision", "multimodal", "mechanistic", "alignment", "safety", "inference",
    "quantiz", "retrieval", "world model", "reinforcement", "fine-tun", "synthetic",
]
_ACTION = [
    "api", "sdk", "app", "available", "download", "试用", "使用", "接入", "工具",
    "product", "plugin", "mcp", "coding", "code", "chat", "studio", "console",
    "dataset", "release", "开源",
]
_NEWS_SIGNAL = [
    "release", "launch", "announce", "introducing", "发布", "上线", "开源",
    "v2", "v3", "v4", "v5", "version", "beta", "ga", "open weights",
]
_CN_KEYWORDS = [
    "中文", "汉语", "字节", "豆包", "通义", "qwen", "deepseek", "minimax", "智谱", "月之暗面",
    "kimi", "国内", "国产", "中国", "volc", "阿里", "百度", "腾讯",
]


def _has_any(text: str, words) -> bool:
    t = text.lower()
    return any(w.lower() in t for w in words)


def score_candidate(c: Candidate) -> float:
    text = f"{c.title_original} {c.summary_original}"
    score = 0.0
    title = c.title_original.lower()

    # 可验证性（来源级别）：A=20, B=12, C=5
    verifiable = {"A": 20.0, "B": 12.0, "C": 5.0}.get(c.source_grade, 8.0)

    # 影响范围（30）：新闻/产品信号 > 研究进展 > 基线
    impact = 0.0
    if _has_any(title, ["release", "launch", "announce", "introducing", "发布", "上线", "开源", "open"]):
        impact += 24.0
    elif _has_any(title, _RESEARCH) and c.source_grade == "A":
        impact += 16.0
    elif _has_any(title, _RESEARCH):
        impact += 12.0
    else:
        impact += 8.0
    if _has_any(text, ["state-of-the-art", "sota", "突破", "超越", "best", "record", "first"]):
        impact += 4.0
    impact = min(30.0, impact)

    # 新颖性（20）：新闻信号词 + 近期加分
    novelty = 0.0
    if _has_any(title, _NEWS_SIGNAL):
        novelty += 12.0
    elif _has_any(title, ["new", "novel", "efficient", "beyond", "toward", "improving", "fast"]):
        novelty += 8.0
    if _has_any(title, _RESEARCH):
        novelty += 4.0
    novelty = min(20.0, novelty + 2.0)

    # 行动价值（20）：可落地/可接入信号
    action = 0.0
    if _has_any(text, _ACTION):
        action += 14.0
    if c.source_grade == "A":
        action += 3.0
    if _has_any(title, ["agent", "coding", "tool", "api", "mcp", "app"]):
        action += 3.0
    action = min(20.0, action)

    # 中文用户相关性（10）
    cn = min(10.0, (8.0 if _has_any(text, _CN_KEYWORDS) else 4.0) + 2.0)

    score = impact + novelty + verifiable + action + cn
    return round(min(100.0, score), 1)


def dedup_merge(candidates: List[Candidate]) -> List[Candidate]:
    """同事件跨源合并：按 dedup_key 合并，保留 A 级一手为主链接。"""
    grade_priority = {"A": 3, "B": 2, "C": 1}
    buckets: Dict[str, List[Candidate]] = {}
    for c in candidates:
        key = c.dedup_key_hint or c.title_original
        dk = make_dedup_key(key, c.category_hint)
        buckets.setdefault(dk, []).append(c)

    merged: List[Candidate] = []
    for dk, group in buckets.items():
        group.sort(key=lambda x: (grade_priority.get(x.source_grade, 0), len(x.summary_original)), reverse=True)
        primary = group[0]
        primary.dedup_key_hint = dk
        # 若一手源缺少摘要，用其它源的摘要补齐
        if not primary.summary_original:
            for other in group[1:]:
                if other.summary_original:
                    primary.summary_original = other.summary_original
                    break
        merged.append(primary)
    return merged


def filter_by_window(candidates: List[Candidate], window_start: str, window_end: str) -> List[Candidate]:
    """内容窗口过滤：有明确发布时间的才进入窗口；无法确定时间的保留待人工/LLM 判断。"""
    start = parse_dt(window_start)
    end = parse_dt(window_end)
    if start is None or end is None:
        return candidates

    out = []
    for c in candidates:
        dt = parse_dt(c.source_published_at)
        if dt is None:
            continue  # 无日期条目不进入（避免陈旧内容）
        dt = dt.astimezone(TZ_SHANGHAI)
        if start <= dt <= end:
            out.append(c)
    return out
