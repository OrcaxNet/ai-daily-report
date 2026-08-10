"""生成步骤：LLM 中文改写候选条目为正式条目（PRD §3.3 / 步骤3）。"""

from __future__ import annotations

import json
import logging
from typing import List, Optional

from .llm import LLMClient, LLMError
from .models import Candidate, Item, CATEGORIES, FACT_TYPES
from .util import make_item_id

log = logging.getLogger(__name__)

_SYSTEM = (
    "你是一名资深 AI 科技新闻编辑，服务对象是中文 AI 从业者与决策者。"
    "请把给定的英文/中文 AI 新闻改写成简洁、准确、有信息增量的中文日报条目。"
    "规则：\n"
    "1) title_cn 为中文标题，忠实原意，不夸大不虚构。\n"
    "2) summary_cn 为 2-3 句中文摘要，只基于给定原文，不得引入原文没有的事实。\n"
    "3) why_it_matters_cn 为「为什么重要」（1-2 句），面向中文从业者/决策者的行动含义。\n"
    "4) tags 为 2-4 个短中文标签。\n"
    "5) category 只能取以下之一：" + "、".join(CATEGORIES) + "。\n"
    "6) fact_type 只能取：事实 / 发布方主张 / 编辑判断（对数字、价格、性能宣称等要标注事实或发布方主张）。\n"
    "7) 涉及数字、价格、许可、安全或监管的关键事实必须与原文字面一致。"
)


def _coerce_category(v: str, fallback: str = "模型进展") -> str:
    if not v:
        return fallback
    for c in CATEGORIES:
        if c in v or v in c:
            return c
    return fallback


def _coerce_fact_type(v: str) -> str:
    if not v:
        return "发布方主张"
    for f in FACT_TYPES:
        if f in v:
            return f
    return "发布方主张"


def _coerce_tags(v) -> List[str]:
    if isinstance(v, list):
        tags = [str(x).strip() for x in v if str(x).strip()]
    elif isinstance(v, str):
        tags = [x.strip() for x in v.replace("，", ",").split(",") if x.strip()]
    else:
        tags = []
    return tags[:5]


def generate_items(candidates: List[Candidate], report_date: str,
                   llm: LLMClient, existing_items: List[Item] = None) -> List[Item]:
    """批量 LLM 生成条目。对每个候选输出结构化字段；字段缺失时降级补默认。"""
    if not candidates:
        return []
    payload = []
    for i, c in enumerate(candidates):
        payload.append({
            "index": i,
            "title_original": c.title_original,
            "summary_original": c.summary_original[:1500],
            "source_name": c.source_name,
            "source_url": c.source_url,
            "published_at": c.source_published_at,
            "source_grade": c.source_grade,
        })

    user = (
        "请为以下每条 AI 新闻生成中文日报条目，输出 JSON："
        '{"items":[{"index":0,"title_cn":"...","summary_cn":"...","why_it_matters_cn":"...","tags":["..."],"category":"...","fact_type":"..."}]}\n'
        + json.dumps(payload, ensure_ascii=False)
    )

    data = llm.messages_json(_SYSTEM, user)
    raw_items = data.get("items", []) if isinstance(data, dict) else []

    by_index = {}
    for it in raw_items:
        if isinstance(it, dict) and "index" in it:
            by_index[int(it["index"])] = it

    items: List[Item] = []
    for i, c in enumerate(candidates):
        g = by_index.get(i, {})
        title_cn = str(g.get("title_cn") or "").strip() or c.title_original
        summary_cn = str(g.get("summary_cn") or "").strip()
        if not summary_cn:
            summary_cn = c.summary_original[:200]
        why = str(g.get("why_it_matters_cn") or "").strip()
        if not why:
            why = "值得关注，建议按需进一步了解原始来源。"
        category = _coerce_category(str(g.get("category") or ""), c.category_hint or "模型进展")
        fact_type = _coerce_fact_type(str(g.get("fact_type") or ""))
        tags = _coerce_tags(g.get("tags")) or ["AI"]
        item = Item(
            item_id=make_item_id(report_date, i, c.dedup_key_hint),
            title_cn=title_cn,
            summary_cn=summary_cn,
            why_it_matters_cn=why,
            tags=tags,
            category=category,
            source_name=c.source_name,
            source_url=c.source_url,
            source_published_at=c.source_published_at,
            collected_at=c.collected_at,
            source_grade=c.source_grade,
            fact_type=fact_type,
            score=0.0,
            dedup_key=c.dedup_key_hint,
            title_original=c.title_original,
        )
        items.append(item)
    return items
