"""
LLM API 客户端抽象层

支持 OpenAI 兼容 API、Ollama。
主要针对国内 AI API 厂商优化（DeepSeek / Moonshot / Qwen 等）。

核心特性：
- 指数退避重试
- HTTP 代理支持
- 厂家预设配置
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from abc import ABC, abstractmethod
from typing import AsyncGenerator, List, Optional

import httpx

from config import get_config

logger = logging.getLogger(__name__)


# ===================================================================
# 可重试的错误类型
# ===================================================================

RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


def _is_retryable(e: Exception) -> bool:
    """判断错误是否值得重试"""
    if isinstance(e, httpx.TimeoutException):
        return True
    if isinstance(e, httpx.HTTPStatusError):
        return e.response.status_code in RETRYABLE_STATUS_CODES
    if isinstance(e, httpx.NetworkError):
        return True
    return False


# ===================================================================
# 消息格式
# ===================================================================

class LLMMessage:
    """统一消息格式"""
    def __init__(self, role: str, content: str):
        self.role = role
        self.content = content

    def to_openai(self) -> dict:
        return {"role": self.role, "content": self.content}


# ===================================================================
# 抽象客户端
# ===================================================================

class LLMClient(ABC):
    """LLM API 抽象基类"""

    @abstractmethod
    async def chat(
        self,
        system_prompt: str,
        messages: List[LLMMessage],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        ...

    @abstractmethod
    async def chat_stream(
        self,
        system_prompt: str,
        messages: List[LLMMessage],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> AsyncGenerator[str, None]:
        ...


# ===================================================================
# OpenAI 兼容客户端（国内厂商都走这个）
# ===================================================================

class OpenAIClient(LLMClient):
    """
    兼容 OpenAI API 格式的客户端
    覆盖 DeepSeek / Moonshot / Qwen / Hunyuan / Spark / ERNIE
    """

    def __init__(self, config: dict):
        self.api_key = config.get("api_key", "")
        self.base_url = config.get("base_url", "https://api.openai.com/v1").rstrip("/")
        self.model = config.get("model", "gpt-4o-mini")
        self.default_temperature = config.get("temperature", 0.8)
        self.default_max_tokens = config.get("max_tokens", 1024)
        self.timeout = config.get("timeout", 60)

        # 重试配置
        retry_cfg = config.get("retry", {})
        self.max_retries = retry_cfg.get("max_retries", 3)
        self.base_delay = retry_cfg.get("base_delay", 1.0)
        self.max_delay = retry_cfg.get("max_delay", 30.0)

        # 熔断器
        self._circuit_open = False
        self._circuit_fails = 0
        self._circuit_threshold = 3  # 连续 3 次失败后熔断
        self._circuit_open_time = 0.0  # 熔断开启时间
        self._circuit_cooldown = 60  # 熔断持续 60 秒

        # 代理（httpx >= 0.28 使用 proxy 参数）
        proxy_url = self._resolve_proxy(config) or None

        self._http_client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(self.timeout),
            proxy=proxy_url,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )

    # ---- 核心接口 ----

    async def chat(
        self,
        system_prompt: str,
        messages: List[LLMMessage],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        import time as _t

        # 熔断检查
        if self._circuit_open:
            if _t.time() - self._circuit_open_time < self._circuit_cooldown:
                raise RuntimeError(f"熔断器开启中（连续{self._circuit_threshold}次失败），请{int(self._circuit_cooldown - (_t.time() - self._circuit_open_time))}秒后重试")
            self._circuit_open = False
            self._circuit_fails = 0

        payload = self._build_payload(system_prompt, messages, temperature, max_tokens)
        last_error = None

        for attempt in range(self.max_retries + 1):
            try:
                resp = await self._http_client.post("/chat/completions", json=payload)
                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"].get("content", "")
                # 成功 → 重置熔断
                self._circuit_fails = 0
                return content.strip() if content else ""

            except Exception as e:
                last_error = e
                if attempt < self.max_retries and _is_retryable(e):
                    delay = min(self.base_delay * (2 ** attempt), self.max_delay)
                    logger.warning(
                        "API 调用失败 (attempt %d/%d), %.1fs 后重试: %s",
                        attempt + 1, self.max_retries + 1, delay, e,
                    )
                    await asyncio.sleep(delay)
                else:
                    break

        # 熔断：连续失败后开启
        import time as _t3
        self._circuit_fails += 1
        if self._circuit_fails >= self._circuit_threshold:
            self._circuit_open = True
            self._circuit_open_time = _t3.time()
            logger.warning("熔断器已开启（连续%d次失败），冷却%d秒", self._circuit_threshold, self._circuit_cooldown)
        logger.error("API 调用最终失败: %s", last_error)
        raise last_error  # type: ignore[misc]

    async def chat_stream(
        self,
        system_prompt: str,
        messages: List[LLMMessage],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> AsyncGenerator[str, None]:
        payload = self._build_payload(system_prompt, messages, temperature, max_tokens)
        payload["stream"] = True

        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                async with self._http_client.stream("POST", "/chat/completions", json=payload) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if line.startswith("data: "):
                            data_str = line[6:].strip()
                            if data_str == "[DONE]":
                                return
                            data = json.loads(data_str)
                            delta = data.get("choices", [{}])[0].get("delta", {})
                            content = delta.get("content", "")
                            if content:
                                yield content
                    return  # 流成功结束

            except Exception as e:
                last_error = e
                if attempt < self.max_retries and _is_retryable(e):
                    delay = min(self.base_delay * (2 ** attempt), self.max_delay)
                    logger.warning(
                        "流式调用失败 (attempt %d/%d), %.1fs 后重试: %s",
                        attempt + 1, self.max_retries + 1, delay, e,
                    )
                    await asyncio.sleep(delay)
                else:
                    break

        logger.error("流式调用最终失败: %s", last_error)
        raise last_error  # type: ignore[misc]

    # ---- 内部 ----

    def _build_payload(self, system_prompt, messages, temperature, max_tokens):
        is_reasoner = "reasoner" in self.model and "v4" not in self.model

        if is_reasoner:
            # DeepSeek reasoner 不支持 system 角色和 temperature
            openai_messages = [{"role": "user", "content": system_prompt}]
            openai_messages.extend(m.to_openai() for m in messages)
            return {
                "model": self.model,
                "messages": openai_messages,
                "max_tokens": max_tokens if max_tokens is not None else self.default_max_tokens,
            }
        else:
            openai_messages = [{"role": "system", "content": system_prompt}]
            openai_messages.extend(m.to_openai() for m in messages)
            return {
                "model": self.model,
                "messages": openai_messages,
                "temperature": temperature if temperature is not None else self.default_temperature,
                "max_tokens": max_tokens if max_tokens is not None else self.default_max_tokens,
            }

    @staticmethod
    def _resolve_proxy(config: dict) -> str | None:
        """从配置和环境变量解析代理 URL（httpx >= 0.28 格式）"""
        proxy = config.get("proxy", {}) or {}

        # 优先 https，其次 http
        for scheme in ("https", "http"):
            url = (
                proxy.get(scheme, "")
                or os.environ.get(f"{scheme.upper()}_PROXY", "")
                or os.environ.get(f"{scheme}_proxy", "")
            )
            if url:
                return url
        return None

    async def close(self):
        await self._http_client.aclose()


# ===================================================================
# Ollama 客户端
# ===================================================================

class OllamaClient(LLMClient):
    """Ollama 本地模型"""

    def __init__(self, config: dict):
        self.base_url = config.get("base_url", "http://localhost:11434").rstrip("/")
        self.model = config.get("model", "qwen2.5:7b")
        self.default_temperature = config.get("temperature", 0.8)
        self.default_max_tokens = config.get("max_tokens", 1024)
        self.timeout = config.get("timeout", 120)

        self._http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(self.timeout),
        )

    async def chat(
        self,
        system_prompt: str,
        messages: List[LLMMessage],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        ollama_messages = [{"role": "system", "content": system_prompt}]
        ollama_messages.extend(m.to_openai() for m in messages)

        payload = {
            "model": self.model,
            "messages": ollama_messages,
            "options": {
                "temperature": temperature if temperature is not None else self.default_temperature,
                "num_predict": max_tokens if max_tokens is not None else self.default_max_tokens,
            },
            "stream": False,
        }

        try:
            resp = await self._http_client.post(f"{self.base_url}/api/chat", json=payload)
            resp.raise_for_status()
            data = resp.json()
            return data["message"]["content"].strip()
        except Exception as e:
            logger.error("Ollama 调用失败: %s", e)
            raise

    async def chat_stream(
        self,
        system_prompt: str,
        messages: List[LLMMessage],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> AsyncGenerator[str, None]:
        ollama_messages = [{"role": "system", "content": system_prompt}]
        ollama_messages.extend(m.to_openai() for m in messages)

        payload = {
            "model": self.model,
            "messages": ollama_messages,
            "options": {
                "temperature": temperature if temperature is not None else self.default_temperature,
            },
            "stream": True,
        }

        try:
            async with self._http_client.stream("POST", f"{self.base_url}/api/chat", json=payload) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.strip():
                        continue
                    data = json.loads(line)
                    content = data.get("message", {}).get("content", "")
                    if content:
                        yield content
                    if data.get("done", False):
                        break
        except Exception as e:
            logger.error("Ollama 流式调用失败: %s", e)
            raise

    async def close(self):
        await self._http_client.aclose()


# ===================================================================
# 工厂函数
# ===================================================================

def create_llm_client(provider: Optional[str] = None) -> LLMClient:
    """创建 LLM 客户端"""
    cfg = get_config()
    llm_cfg = cfg.llm
    provider = provider or llm_cfg.get("provider", "openai")

    if provider == "ollama":
        return OllamaClient(llm_cfg)
    else:
        # deepseek / moonshot / qwen / hunyuan / spark / ernie …
        # 全都走 OpenAI 兼容格式
        return OpenAIClient(llm_cfg)
