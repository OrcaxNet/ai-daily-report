"""数据模型（PRD §3.1 字段契约）。"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional


# 栏目枚举（PRD §4.2）
CATEGORIES = ["基础理论", "模型进展", "Agent 进展", "AI 应用", "可选观察"]
CORE_CATEGORIES = ["基础理论", "模型进展", "Agent 进展", "AI 应用"]

# 事实类型（PRD §3.3）
FACT_TYPES = ["事实", "发布方主张", "编辑判断"]

# 来源级别
GRADE_A = "A"
GRADE_B = "B"
GRADE_C = "C"


@dataclass
class Candidate:
    """采集到的候选条目（未打分、未生成）。"""

    source_name: str
    source_url: str
    source_published_at: str          # ISO 8601 或空串（无法确定日期）
    collected_at: str                 # ISO 8601
    source_grade: str                 # A / B / C
    title_original: str
    summary_original: str
    category_hint: str = ""           # 采集时的栏目猜测
    dedup_key_hint: str = ""
    raw: dict = field(default_factory=dict)


@dataclass
class Item:
    """最终入选条目（PRD §3.1 条目级字段）。"""

    item_id: str
    title_cn: str
    summary_cn: str
    why_it_matters_cn: str
    tags: list
    category: str
    source_name: str
    source_url: str
    source_published_at: str
    collected_at: str
    source_grade: str
    fact_type: str
    score: float
    dedup_key: str
    title_original: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Report:
    """一期日报（报告级元数据 + 条目）。"""

    report_date: str                  # YYYY-MM-DD（Asia/Shanghai）
    generated_at: str
    content_window_start: str
    content_window_end: str
    item_count: int
    category_counts: dict
    corrections: list
    data_cutoff: str
    ai_disclosure: str
    items: list
    empty_categories: list = field(default_factory=list)
    insufficient_note: Optional[str] = None
    grace_note: Optional[str] = None
    generation: dict = field(default_factory=dict)   # token/耗时等元信息

    def to_dict(self) -> dict:
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Report":
        d = dict(d)
        items = [Item(**it) if isinstance(it, dict) else it for it in d.get("items", [])]
        d["items"] = items
        return cls(**d)
