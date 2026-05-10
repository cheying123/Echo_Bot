"""
两段式台词检索器

粗筛（TF-IDF）→ 精筛（向量语义重排序）

零本地模型依赖，全部走 API embedding。
"""

from __future__ import annotations

import logging
import math
import re
from collections import Counter
from typing import List, Optional, Tuple

from core.embeddings import EmbeddingStore

logger = logging.getLogger(__name__)


class TwoStageRetriever:
    """
    两段式检索器

    用法：
        retriever = TwoStageRetriever(db_path)
        results = await retriever.retrieve("心情不好", dialogues, top_k=5)
    """

    def __init__(self, db_path: str = ""):
        from config import get_config
        cfg = get_config()
        self._db_path = db_path or cfg.paths.get("db_path", "data/bot.db")
        self._embed_store: Optional[EmbeddingStore] = None
        self._embed_ready = False

    async def _get_store(self) -> EmbeddingStore:
        if self._embed_store is None:
            self._embed_store = EmbeddingStore(self._db_path)
        return self._embed_store

    async def retrieve(
        self,
        query: str,
        dialogues: List[str],
        top_k: int = 5,
    ) -> List[Tuple[str, float]]:
        if not dialogues or not query:
            return []

        # === 第一段：TF-IDF 粗筛 ===
        candidates = self._rough_filter(query, dialogues, top_k=20)
        if not candidates:
            return []

        # === 第二段：向量精筛 ===
        try:
            store = await self._get_store()
            # 获取 candidates 的 embedding
            cand_texts = [c[0] for c in candidates]
            vecs = await store.get_embeddings_batch(cand_texts)

            # 查询向量
            q_vec = await store.get_embedding(query)
            if q_vec and vecs:
                scored = []
                for text in cand_texts:
                    v = vecs.get(text)
                    if v:
                        score = store.cosine_similarity(q_vec, v)
                        scored.append((text, score))
                scored.sort(key=lambda x: x[1], reverse=True)
                return scored[:top_k]
        except Exception as e:
            logger.debug("向量精筛失败: %s，返回粗筛结果", e)

        return candidates[:top_k]

    # ---- 粗筛：TF-IDF ----

    STOP_CHARS = frozenset({"的", "了", "在", "是", "有", "和", "就", "不", "都", "也",
                            "很", "到", "着", "呢", "吧", "吗", "啊", "哦", "嗯", "啦",
                            "嘛", "呀", "哟", "呵", "哈", "哇", "喔", "哎", "诶", "噢",
                            "呃", "呜", "呐", "咯", "喽"})

    def _rough_filter(self, query: str, dialogues: List[str], top_k: int = 20) -> List[Tuple[str, float]]:
        """TF-IDF 粗筛，召回 top_k 条候选"""
        query_ngrams = self._extract_ngrams(query)
        if not query_ngrams:
            return []

        idf = self._compute_idf(dialogues)
        q_vec = self._tfidf(query_ngrams, idf)

        scored = []
        for line in dialogues:
            line_ngrams = self._extract_ngrams(line)
            if not line_ngrams:
                continue
            l_vec = self._tfidf(line_ngrams, idf)
            score = self._cosine_sim(q_vec, l_vec)
            if score > 0:
                scored.append((line, score))

        scored.sort(key=lambda x: x[1], reverse=True)
        # 去重
        unique = []
        seen = set()
        for line, score in scored:
            prefix = line[:20]
            if prefix not in seen:
                seen.add(prefix)
                unique.append((line, score))
        return unique[:top_k]

    def _extract_ngrams(self, text: str) -> Counter:
        chars = [c for c in text if '一' <= c <= '鿿']
        if not chars:
            return Counter()
        ngrams: Counter = Counter()
        for c in chars:
            if c not in self.STOP_CHARS:
                ngrams[c] += 1
        for i in range(len(chars) - 1):
            ngrams[chars[i] + chars[i + 1]] += 1
        return ngrams

    def _compute_idf(self, dialogues: List[str]) -> dict[str, float]:
        n = len(dialogues)
        df: Counter = Counter()
        for line in dialogues:
            ngrams = self._extract_ngrams(line)
            for token in ngrams:
                df[token] += 1
        return {t: math.log(n / max(d, 1)) + 1 for t, d in df.items()}

    @staticmethod
    def _tfidf(ngrams: Counter, idf: dict[str, float]) -> dict[str, float]:
        max_tf = max(ngrams.values()) if ngrams else 1
        return {t: (c / max_tf) * idf.get(t, 1.0) for t, c in ngrams.items()}

    @staticmethod
    def _cosine_sim(a: dict[str, float], b: dict[str, float]) -> float:
        dot = sum(ak * b.get(k, 0) for k, ak in a.items())
        na = math.sqrt(sum(v * v for v in a.values()))
        nb = math.sqrt(sum(v * v for v in b.values()))
        if na * nb == 0:
            return 0.0
        return dot / (na * nb)


# ===================================================================
# 原 TF-IDF 检索器（兼容旧代码、同步调用）
# ===================================================================

class DialogueRetriever:
    """纯 TF-IDF 检索器，零依赖，用于同步场景"""

    STOP_CHARS = TwoStageRetriever.STOP_CHARS

    def retrieve(self, query: str, dialogues: list[str], top_k: int = 5) -> list[tuple[str, float]]:
        tsr = TwoStageRetriever()
        return tsr._rough_filter(query, dialogues, top_k)
