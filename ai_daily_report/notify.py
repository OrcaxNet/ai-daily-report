"""通知与留痕（PRD 步骤7 / §5.4）：写入 run 日志，供 autopilot 评论留痕。"""

from __future__ import annotations

import logging
from typing import Optional

from .state import StateStore

log = logging.getLogger(__name__)


def record_run(state_store: StateStore, date: str, outcome: str, step: str,
               message: str, details: Optional[dict] = None) -> None:
    """outcome: success | failed；details 含各步骤统计/耗时/错误。"""
    from .util import now_shanghai, fmt_iso
    entry = {
        "date": date,
        "outcome": outcome,
        "step": step,
        "message": message,
        "ts": fmt_iso(now_shanghai()),
        "details": details or {},
    }
    state_store.write_run_log(date, entry)
    log.info("run record %s %s @%s: %s", date, outcome, step, message)


def build_notice_text(state_store: StateStore, date: str, outcome: str, step: str,
                      message: str, details: Optional[dict] = None) -> str:
    """生成给负责人的人工可读通知文本。"""
    prev = state_store.load().get("last_published_date", "")
    lines = [
        f"AI 日报 {date}：{outcome}",
        f"失败/记录环节：{step}",
        f"说明：{message}",
        f"上一期状态：{prev or '无'}",
    ]
    if details:
        lines.append("详情：" + ", ".join(f"{k}={v}" for k, v in details.items()))
    return "\n".join(lines)
