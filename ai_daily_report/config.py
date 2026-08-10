"""配置加载：来源白名单 + LLM 配置 + 运行时密钥解析。"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent


class ConfigError(Exception):
    pass


def load_sources(path: Optional[Path] = None) -> dict:
    path = path or (REPO_ROOT / "config" / "sources.yaml")
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    sources = data.get("sources", {})
    enabled = {name: cfg for name, cfg in sources.items() if cfg.get("enabled", True)}
    return {"collection": data.get("collection", {}), "sources": enabled}


def load_llm(path: Optional[Path] = None) -> dict:
    path = path or (REPO_ROOT / "config" / "llm.yaml")
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data.get("llm", {})


def _read_arkcli_config() -> dict:
    """读取本机 ~/.arkcli/config.yaml（含 coding-plan API key / base_url）。"""
    p = Path.home() / ".arkcli" / "config.yaml"
    if not p.exists():
        return {}
    try:
        with open(p, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def resolve_coding_plan_credentials() -> dict:
    """解析火山方舟 Coding Plan 的 API Key 与 Base URL。

    优先级：
    1. 环境变量 ARK_CODING_API_KEY / ARK_CODING_BASE_URL
    2. ~/.arkcli/config.yaml 中 coding-plan 类型 profile 的 api_key / anthropic_base_url
    """
    api_key = os.environ.get("ARK_CODING_API_KEY", "").strip()
    base_url = os.environ.get("ARK_CODING_BASE_URL", "").strip()

    if not api_key or not base_url:
        cfg = _read_arkcli_config()
        for profile in cfg.get("profiles", {}).values():
            if profile.get("type") == "coding-plan":
                api_key = api_key or profile.get("api_key", "")
                base_url = base_url or profile.get("anthropic_base_url", "")
                break
        # 兜底：直接用环境里 ARK_API_KEY（未来若指向有效 coding key）
        if not api_key:
            api_key = os.environ.get("ARK_API_KEY", "").strip()
        if not base_url:
            base_url = "https://ark.cn-beijing.volces.com/api/coding"

    if not api_key:
        raise ConfigError(
            "无法解析 ARK Coding Plan API Key：请设置 ARK_CODING_API_KEY，"
            "或在本机 ~/.arkcli/config.yaml 配置 coding-plan profile。"
        )
    return {"api_key": api_key, "base_url": base_url.rstrip("/")}
