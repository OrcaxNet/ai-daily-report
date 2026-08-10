"""LLM 客户端：火山方舟 Coding Plan（Anthropic 兼容 Messages API）。

用于生成步骤的中文改写（标题/摘要/为什么重要/标签/事实类型）。
密钥从本机 ~/.arkcli 解析或环境变量注入，不落库。
"""

from __future__ import annotations

import json
import logging
import time
from typing import Optional

import requests

from .config import resolve_coding_plan_credentials

log = logging.getLogger(__name__)


class LLMError(Exception):
    pass


class CostGuardExceeded(LLMError):
    pass


class LLMClient:
    def __init__(self, llm_cfg: dict, api_key: str = "", base_url: str = "", model: str = ""):
        creds = resolve_coding_plan_credentials() if not (api_key and base_url) else {"api_key": api_key, "base_url": base_url}
        self.api_key = api_key or creds["api_key"]
        self.base_url = base_url or creds["base_url"]
        if self.base_url.endswith("/v1"):
            self.base_url = self.base_url[:-3]
        self.model = model or llm_cfg.get("model", "claude-sonnet-4-20250514")
        self.max_tokens = int(llm_cfg.get("max_tokens", 6000))
        self.temperature = float(llm_cfg.get("temperature", 0.3))
        self.cost_guard = llm_cfg.get("cost_guard", {})
        self._call_count = 0
        self._token_total = 0

    def check_guard(self):
        max_calls = int(self.cost_guard.get("max_calls_per_run", 12))
        max_tokens = int(self.cost_guard.get("max_tokens_per_run", 120000))
        if self._call_count >= max_calls:
            raise CostGuardExceeded(f"LLM call guard exceeded ({max_calls})")
        if self._token_total >= max_tokens:
            raise CostGuardExceeded(f"LLM token guard exceeded ({max_tokens})")

    def messages(self, system: str, user: str, max_tokens: Optional[int] = None,
                 json_mode: bool = False, temperature: Optional[float] = None) -> str:
        self.check_guard()
        url = f"{self.base_url}/v1/messages"
        payload = {
            "model": self.model,
            "max_tokens": max_tokens or self.max_tokens,
            "temperature": self.temperature if temperature is None else temperature,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        try:
            t0 = time.time()
            resp = requests.post(url, json=payload, headers=headers, timeout=180)
            elapsed = time.time() - t0
        except requests.RequestException as e:
            raise LLMError(f"LLM request failed: {e}") from e
        if resp.status_code != 200:
            raise LLMError(f"LLM HTTP {resp.status_code}: {resp.text[:300]}")
        try:
            data = resp.json()
            text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
            usage = data.get("usage", {})
        except Exception as e:  # noqa: BLE001
            raise LLMError(f"LLM parse failed: {e}") from e

        self._call_count += 1
        self._token_total += int(usage.get("input_tokens", 0)) + int(usage.get("output_tokens", 0))
        log.info("LLM call #%d elapsed=%.1fs in=%s out=%s cache_in=%s",
                 self._call_count, elapsed, usage.get("input_tokens"), usage.get("output_tokens"),
                 usage.get("cache_read_input_tokens"))
        return text.strip()

    def messages_json(self, system: str, user: str, **kw) -> dict:
        """要求模型输出一个 JSON 对象；解析失败抛 LLMError。"""
        text = self.messages(system, user + "\n\n请只输出一个合法的 JSON 对象，不要包含任何其他文字、代码围栏或注释。", **kw)
        text = text.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            # 尝试抽取 {...} 片段
            s, epos = text.find("{"), text.rfind("}")
            if s != -1 and epos != -1:
                try:
                    return json.loads(text[s:epos + 1])
                except json.JSONDecodeError:
                    pass
            raise LLMError(f"LLM JSON parse failed: {e}; text={text[:200]}")

    @property
    def usage(self) -> dict:
        return {"calls": self._call_count, "tokens": self._token_total}
