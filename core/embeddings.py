"""
向量嵌入缓存：SQLite 存储 + API 调用

存储所有角色台词和关键对话的 embedding，避免重复计算。
调 DeepSeek 的 embedding API，零本地资源消耗。
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import sqlite3
import time
from typing import List, Optional, Tuple

import httpx

from config import get_config

logger = logging.getLogger(__name__)


class EmbeddingStore:
    """
    embedding 存储与检索

    SQLite 中建表：
      embeddings(text_hash TEXT PK, text TEXT, vector TEXT, source TEXT, char_id TEXT, created_at TEXT)
    """

    def __init__(self, db_path: str):
        self._db_path = db_path
        self._init_db()
        # API 客户端缓存
        self._api_client: Optional[httpx.AsyncClient] = None

    def _init_db(self):
        conn = sqlite3.connect(self._db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS embeddings (
                text_hash TEXT PRIMARY KEY,
                text TEXT NOT NULL,
                vector TEXT NOT NULL,
                source TEXT DEFAULT 'dialogue',
                char_id TEXT DEFAULT '',
                created_at TEXT NOT NULL
            )
        """)
        conn.commit()
        conn.close()

    def _hash(self, text: str) -> str:
        return hashlib.md5(text.encode()).hexdigest()

    async def _get_client(self) -> httpx.AsyncClient:
        if self._api_client is None:
            cfg = get_config().llm
            api_key = cfg.get("api_key", "")
            base_url = cfg.get("base_url", "https://api.openai.com/v1").rstrip("/")
            self._api_client = httpx.AsyncClient(
                base_url=base_url,
                timeout=30.0,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            )
        return self._api_client

    async def get_embedding(self, text: str) -> Optional[List[float]]:
        """获取文本的 embedding（优先缓存，不中则调 API）"""
        h = self._hash(text)
        # 查缓存
        vec = self._get_cached(h)
        if vec is not None:
            return vec
        # 调 API
        vec = await self._fetch_embedding(text)
        if vec:
            self._save(h, text, vec, "dialogue", "")
        return vec

    async def get_embeddings_batch(self, texts: List[str]) -> dict[str, List[float]]:
        """批量获取 embedding，返回 {text: vector}"""
        result = {}
        uncached = []
        for t in texts:
            h = self._hash(t)
            vec = self._get_cached(h)
            if vec:
                result[t] = vec
            else:
                uncached.append(t)

        if uncached:
            vectors = await self._fetch_embeddings_batch(uncached)
            if vectors:
                for t, vec in zip(uncached, vectors):
                    if vec:
                        self._save(self._hash(t), t, vec, "dialogue", "")
                        result[t] = vec
        return result

    def _get_cached(self, text_hash: str) -> Optional[List[float]]:
        try:
            conn = sqlite3.connect(self._db_path)
            row = conn.execute("SELECT vector FROM embeddings WHERE text_hash=?", (text_hash,)).fetchone()
            conn.close()
            if row:
                return json.loads(row[0])
        except Exception:
            pass
        return None

    def _save(self, text_hash: str, text: str, vector: List[float], source: str, char_id: str):
        try:
            conn = sqlite3.connect(self._db_path)
            conn.execute(
                "INSERT OR REPLACE INTO embeddings VALUES (?,?,?,?,?,?)",
                (text_hash, text, json.dumps(vector), source, char_id, time.strftime("%Y-%m-%d %H:%M:%S")),
            )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.debug("保存 embedding 失败: %s", e)

    async def _fetch_embedding(self, text: str) -> Optional[List[float]]:
        """调 API 获取单条 embedding"""
        try:
            client = await self._get_client()
            for model in ["text-embedding-v2", "text-embedding-v1", "text-embedding-ada-002"]:
                resp = await client.post("/embeddings", json={"model": model, "input": text})
                if resp.status_code == 200:
                    return resp.json()["data"][0]["embedding"]
                await asyncio.sleep(0.5)
            return None
        except Exception as e:
            logger.debug("embedding API 调用失败: %s", e)
            return None

    async def _fetch_embeddings_batch(self, texts: List[str]) -> Optional[List[List[float]]]:
        """批量调 API 获取 embedding"""
        if not texts:
            return None
        try:
            client = await self._get_client()
            for model in ["text-embedding-v2", "text-embedding-v1", "text-embedding-ada-002"]:
                resp = await client.post("/embeddings", json={"model": model, "input": texts})
                if resp.status_code == 200:
                    data = resp.json()["data"]
                    data.sort(key=lambda x: x["index"])
                    return [item["embedding"] for item in data]
                await asyncio.sleep(0.5)
            return None
        except Exception as e:
            logger.debug("batch embedding 失败: %s", e)
            return None

    async def preload_dialogues(self, dialogues: List[str], char_id: str):
        """预计算角色台词的 embedding"""
        texts = [d for d in dialogues if self._get_cached(self._hash(d)) is None]
        if not texts:
            return
        logger.info("预计算 %d 条台词 embedding...", len(texts))
        vectors = await self._fetch_embeddings_batch(texts)
        if vectors:
            for t, vec in zip(texts, vectors):
                if vec:
                    self._save(self._hash(t), t, vec, "dialogue", char_id)

    def cosine_similarity(self, a: List[float], b: List[float]) -> float:
        """余弦相似度"""
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(y * y for y in b))
        if na * nb == 0:
            return 0.0
        return dot / (na * nb)


import asyncio  # noqa: E402
