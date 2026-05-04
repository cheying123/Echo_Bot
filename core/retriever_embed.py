"""
语义嵌入检索器（同步 API 版）

使用 AI 厂商的 embedding API，零本地资源消耗。

流程：
  1. 首次使用时对角色台词库批量计算 embedding
  2. 缓存到内存
  3. 每次对话只查询向量
  4. 余弦相似度排序取 Top-5
  5. API 不可用时降级到 TF-IDF
"""

from __future__ import annotations

import json
import logging
from typing import List, Optional, Tuple, Union

import httpx

from config import get_config
from core.retriever import DialogueRetriever as TfidfRetriever

logger = logging.getLogger(__name__)


class APIEmbeddingRetriever:
    """使用 AI 厂商 embedding API 做语义检索"""

    def __init__(self):
        self._fallback = TfidfRetriever()
        self._embeddings: dict[str, list[float]] = {}
        self._batch_size = 10

    def _call_embed_api(self, texts: list[str]) -> Optional[list[list[float]]]:
        """调用 embedding API（同步）"""
        cfg = get_config().llm
        api_key = cfg.get("api_key", "")
        base_url = cfg.get("base_url", "https://api.openai.com/v1").rstrip("/")

        try:
            with httpx.Client(
                base_url=base_url,
                timeout=30.0,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
            ) as client:
                for model in ["text-embedding-v2", "text-embedding-v1", "text-embedding-ada-002"]:
                    resp = client.post("/embeddings", json={
                        "model": model,
                        "input": texts,
                    })
                    if resp.status_code == 200:
                        data = resp.json()
                        sorted_data = sorted(data["data"], key=lambda x: x["index"])
                        return [item["embedding"] for item in sorted_data]
                else:
                    logger.debug("Embedding API 无可用模型")
                    return None
        except Exception as e:
            logger.debug("Embedding API 调用失败: %s", e)
            return None

    def preload(self, dialogues: list[str]):
        """预计算台词 embedding"""
        new_d = [d for d in dialogues if d not in self._embeddings]
        if not new_d:
            return
        logger.info("预计算 %d 条台词的 embedding...", len(new_d))
        for i in range(0, len(new_d), self._batch_size):
            batch = new_d[i:i + self._batch_size]
            vecs = self._call_embed_api(batch)
            if vecs:
                for d, v in zip(batch, vecs):
                    self._embeddings[d] = v

    def retrieve(
        self,
        query: str,
        dialogues: list[str],
        top_k: int = 5,
    ) -> list[tuple[str, float]]:
        if not dialogues or not query:
            return []

        try:
            self.preload(dialogues)
            if not self._embeddings:
                return self._fallback.retrieve(query, dialogues, top_k)

            import math as m

            # 查询向量
            q_vecs = self._call_embed_api([query])
            if q_vecs is None:
                return self._fallback.retrieve(query, dialogues, top_k)

            q = q_vecs[0]
            q_norm = m.sqrt(sum(v * v for v in q))

            scored = []
            for d in dialogues:
                v = self._embeddings.get(d)
                if not v:
                    continue
                dot = sum(a * b for a, b in zip(q, v))
                v_norm = m.sqrt(sum(a * a for a in v))
                if v_norm == 0 or q_norm == 0:
                    continue
                scored.append((d, dot / (q_norm * v_norm)))

            scored.sort(key=lambda x: x[1], reverse=True)
            return scored[:top_k]

        except Exception as e:
            logger.debug("API Embedding 失败: %s -> TF-IDF", e)
            return self._fallback.retrieve(query, dialogues, top_k)
