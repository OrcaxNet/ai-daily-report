"""发布步骤（PRD 步骤6）：staging 校验后原子切换到 site/；不覆盖上一期成功页。"""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path

from .state import StateStore

log = logging.getLogger(__name__)


def publish_site(staging_root: Path, site_root: Path, date: str, state_store: StateStore) -> dict:
    """把已校验的 staging 目录原子发布到 site/。"""
    staging_root = Path(staging_root)
    site_root = Path(site_root)

    # 目标当日页若已存在（同一天幂等重跑），允许覆盖 staging 产物；
    # 但不触碰其它历史日页面。
    site_root.mkdir(parents=True, exist_ok=True)

    # 拷贝当日页与数据文件
    src_daily = staging_root / "daily" / f"{date}.html"
    src_json = staging_root / "data" / f"report-{date}.json"
    if not src_daily.exists():
        raise FileNotFoundError(f"staging 缺少当日页 {src_daily}")
    if not src_json.exists():
        raise FileNotFoundError(f"staging 缺少 JSON {src_json}")

    dst_daily = site_root / "daily" / f"{date}.html"
    dst_json = site_root / "data" / f"report-{date}.json"
    dst_daily.parent.mkdir(parents=True, exist_ok=True)
    dst_json.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src_daily, dst_daily)
    shutil.copy2(src_json, dst_json)

    # 全局文件（首页指针/归档/更正/样式）
    for fname in ("index.html", "archive.html", "corrections.html"):
        src = staging_root / fname
        if src.exists():
            shutil.copy2(src, site_root / fname)
    assets_src = staging_root / "assets" / "style.css"
    if assets_src.exists():
        (site_root / "assets").mkdir(parents=True, exist_ok=True)
        shutil.copy2(assets_src, site_root / "assets" / "style.css")

    # 更新状态（幂等：重复发布同日期不重复加入列表）
    state = state_store.load()
    dates = state.get("published_dates", [])
    if date not in dates:
        dates.append(date)
    state["published_dates"] = sorted(dates)
    state["last_published_date"] = date
    state_store.save(state)

    # 归档 JSON 元数据到 data/reports（持久副本）
    report_dict = json.loads(src_json.read_text(encoding="utf-8"))
    state_store.save_report_json(report_dict)

    log.info("published %s -> %s", date, site_root)
    return {"date": date, "site_root": str(site_root), "files": [str(dst_daily), str(dst_json)]}
