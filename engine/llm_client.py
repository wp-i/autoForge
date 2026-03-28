"""
engine/llm_client.py
小米 MIMO API 统一调用层.

封装所有与 LLM 的交互, 对上层模块暴露简洁的 chat() / chat_json() 接口.
使用 httpx 异步客户端, 兼容 OpenAI Chat Completions 格式.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any

import httpx

logger = logging.getLogger("autoforge.llm")


# ------------------------------------------------------------------
# Data structures
# ------------------------------------------------------------------
@dataclass
class Message:
    role: str  # "system" | "user" | "assistant"
    content: str


@dataclass
class LLMConfig:
    api_key: str
    base_url: str
    model: str
    temperature: float = 0.3
    max_tokens: int = 8192


# ------------------------------------------------------------------
# Client
# ------------------------------------------------------------------
class LLMClient:
    """与小米 MIMO Chat Completions API 交互的同步/异步客户端."""

    def __init__(self, config: LLMConfig | None = None) -> None:
        if config is None:
            config = self._from_env()
        self.cfg = config
        self._endpoint = f"{self.cfg.base_url.rstrip('/')}/v1/chat/completions"
        self._headers = {
            "Authorization": f"Bearer {self.cfg.api_key}",
            "Content-Type": "application/json",
        }
        logger.info(
            "LLMClient ready  model=%s  endpoint=%s",
            self.cfg.model,
            self._endpoint,
        )

    # ---------- public API ----------

    def chat(
        self,
        messages: list[Message],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        """发送对话并返回纯文本回复."""
        payload = self._build_payload(messages, temperature, max_tokens)
        resp = self._post(payload)
        return self._extract_text(resp)

    def chat_json(
        self,
        messages: list[Message],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        """发送对话并解析 JSON 回复.

        若 LLM 返回的内容不是合法 JSON, 尝试提取 ```json 代码块.
        """
        raw = self.chat(messages, temperature=temperature, max_tokens=max_tokens)
        return self._parse_json(raw)

    # ---------- internal ----------

    @staticmethod
    def _from_env() -> LLMConfig:
        api_key = os.environ.get("AUToforge_LLM_API_KEY", "")
        base_url = os.environ.get("AUToforge_LLM_BASE_URL", "")
        model = os.environ.get("AUToforge_MODEL_NAME", "MiMo-V2-Pro")
        if not api_key or not base_url:
            raise EnvironmentError(
                "Missing AUToforge_LLM_API_KEY or AUToforge_LLM_BASE_URL in .env"
            )
        return LLMConfig(api_key=api_key, base_url=base_url, model=model)

    def _build_payload(
        self,
        messages: list[Message],
        temperature: float | None,
        max_tokens: int | None,
    ) -> dict[str, Any]:
        return {
            "model": self.cfg.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": temperature
            if temperature is not None
            else self.cfg.temperature,
            "max_tokens": max_tokens if max_tokens is not None else self.cfg.max_tokens,
        }

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        logger.debug(
            "POST %s  tokens_limit=%s", self._endpoint, payload.get("max_tokens")
        )
        with httpx.Client(timeout=180) as client:
            r = client.post(self._endpoint, headers=self._headers, json=payload)
            r.raise_for_status()
            return r.json()

    @staticmethod
    def _extract_text(resp: dict[str, Any]) -> str:
        try:
            return resp["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as exc:
            logger.error("Unexpected API response structure: %s", resp)
            raise ValueError("Cannot extract text from API response") from exc

    @staticmethod
    def _parse_json(raw: str) -> dict[str, Any]:
        """尽力从 LLM 回复中提取 JSON 对象."""
        # 1) 尝试直接解析
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass

        # 2) 提取 ```json ... ``` 代码块
        if "```json" in raw:
            start = raw.index("```json") + 7
            end = raw.index("```", start)
            return json.loads(raw[start:end].strip())

        # 3) 提取第一个 { ... } 块
        brace_start = raw.find("{")
        brace_end = raw.rfind("}")
        if brace_start != -1 and brace_end != -1:
            return json.loads(raw[brace_start : brace_end + 1])

        raise ValueError(f"LLM response is not valid JSON:\n{raw[:500]}")
