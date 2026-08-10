"""通用工具：时区、HTTP、哈希。"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests

TZ_SHANGHAI = timezone(timedelta(hours=8), name="Asia/Shanghai")


def now_shanghai() -> datetime:
    return datetime.now(TZ_SHANGHAI)


def fmt_iso(dt: datetime) -> str:
    return dt.astimezone(TZ_SHANGHAI).isoformat(timespec="seconds")


def window_for(date_str: str) -> tuple[str, str]:
    """内容窗口：前一日 06:30 -> 当日 06:30（Asia/Shanghai，PRD D2）。

    数据截止（data_cutoff）= 当日 06:30；窗口起点 = 截止前 24 小时。
    """
    d = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=TZ_SHANGHAI)
    end = d.replace(hour=6, minute=30, second=0, microsecond=0)
    start = end - timedelta(hours=24)
    return fmt_iso(start), fmt_iso(end)


def parse_dt(value: str) -> Optional[datetime]:
    """宽松解析日期字符串，失败返回 None。"""
    if not value:
        return None
    v = value.strip()
    for fmt in (
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d",
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S GMT",
        "%B %d, %Y",
        "%b %d, %Y",
    ):
        try:
            return datetime.strptime(v, fmt)
        except ValueError:
            continue
    return None


def normalize_title(title: str) -> str:
    """用于去重的标题归一化：小写、去标点、去空白。"""
    s = title.lower()
    s = re.sub(r"[^\w\u4e00-\u9fff]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def make_dedup_key(title: str, category_hint: str = "") -> str:
    base = normalize_title(title)
    return hashlib.sha1(f"{base}|{category_hint}".encode("utf-8")).hexdigest()[:16]


def make_item_id(report_date: str, index: int, seed: str) -> str:
    raw = f"{report_date}-{index}-{seed}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


class HttpError(Exception):
    pass


def http_get(url: str, timeout: int = 15, headers: Optional[dict] = None) -> requests.Response:
    """带 UA 与重定向跟随的 GET；失败抛 HttpError。"""
    h = {
        "User-Agent": "Mozilla/5.0 (compatible; AIDailyReport/1.0; +https://github.com/OrcaxNet/ai-daily-report)",
        "Accept": "*/*",
    }
    if headers:
        h.update(headers)
    try:
        resp = requests.get(url, timeout=timeout, headers=h, allow_redirects=True)
    except requests.RequestException as e:
        raise HttpError(f"GET {url}: {e}") from e
    if resp.status_code >= 400:
        raise HttpError(f"GET {url}: HTTP {resp.status_code}")
    return resp


def safe_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
