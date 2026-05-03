"""
台词检索器：从角色台词库中检索与当前话题最相关的台词

使用字符级 n-gram（1-gram + 2-gram）TF-IDF + 余弦相似度。
零外部依赖，专为中文对话优化。
"""

from __future__ import annotations

import logging
import math
import re
from collections import Counter
from typing import List, Tuple

logger = logging.getLogger(__name__)


class DialogueRetriever:
    """
    台词检索器

    用法：
        retriever = DialogueRetriever()
        best = retriever.retrieve("你好呀", source_dialogues, top_k=5)
    """

    # 仅过滤纯语气/结构助词（不包含 你/我/他/她 等代词）
    STOP_CHARS = frozenset({
        "的", "了", "在", "是", "有", "和", "就", "不", "都", "也",
        "很", "到", "着", "呢", "吧", "吗", "啊", "哦", "嗯", "啦",
        "嘛", "呀", "哟", "呵", "哈", "哇", "喔", "哎", "诶", "噢",
        "呃", "呜", "呐", "咯", "喽", "呵",
    })

    def retrieve(
        self,
        query: str,
        dialogues: List[str],
        top_k: int = 5,
    ) -> List[Tuple[str, float]]:
        """
        从台词库中检索与 query 最相关的台词。

        Args:
            query: 用户当前消息
            dialogues: 角色台词库列表
            top_k: 返回前多少条

        Returns:
            [(台词, 相似度分数), ...]
        """
        if not dialogues or not query:
            return []

        # 提取查询的 n-gram 特征
        query_ngrams = self._extract_ngrams(query)
        if not query_ngrams:
            return []

        # 计算台词库的 IDF
        idf = self._compute_idf(dialogues)

        # 查询向量
        query_vec = self._tfidf(query_ngrams, idf)

        # 计算每条台词的相似度
        scored = []
        for line in dialogues:
            line_ngrams = self._extract_ngrams(line)
            if not line_ngrams:
                continue
            line_vec = self._tfidf(line_ngrams, idf)
            score = self._cosine_sim(query_vec, line_vec)
            if score > 0:
                scored.append((line, score))

        # 按分数降序
        scored.sort(key=lambda x: x[1], reverse=True)

        # 去重（去掉开头过于相似的台词）
        unique = []
        seen_prefixes = set()
        for line, score in scored:
            prefix = line[:15]
            if prefix not in seen_prefixes:
                seen_prefixes.add(prefix)
                unique.append((line, score))
                if len(unique) >= top_k:
                    break

        return unique[:top_k]

    # ---- 特征提取 ----

    def _extract_ngrams(self, text: str) -> Counter:
        """
        提取字符级 1-gram + 2-gram。
        只保留中文字符，过滤纯语气助词 1-gram。
        """
        # 只保留中文字符
        chars = [c for c in text if '一' <= c <= '鿿']
        if not chars:
            return Counter()

        ngrams: Counter = Counter()

        # 1-gram：保留所有非停用字的汉字
        for c in chars:
            if c not in self.STOP_CHARS:
                ngrams[c] += 1

        # 2-gram：全部保留
        for i in range(len(chars) - 1):
            bigram = chars[i] + chars[i + 1]
            ngrams[bigram] += 1

        return ngrams

    # ---- TF-IDF ----

    def _compute_idf(self, dialogues: List[str]) -> dict[str, float]:
        """计算台词库的 IDF"""
        n = len(dialogues)
        if n == 0:
            return {}

        df: Counter = Counter()
        for line in dialogues:
            ngrams = self._extract_ngrams(line)
            for token in ngrams:
                df[token] += 1

        # IDF = log(N / df) + 1  （平滑）
        idf = {}
        for token, doc_freq in df.items():
            idf[token] = math.log(n / max(doc_freq, 1)) + 1

        return idf

    @staticmethod
    def _tfidf(ngrams: Counter, idf: dict[str, float]) -> dict[str, float]:
        """TF-IDF 向量化"""
        max_tf = max(ngrams.values()) if ngrams else 1
        vec = {}
        for token, count in ngrams.items():
            tf = count / max_tf
            idf_val = idf.get(token, 1.0)
            vec[token] = tf * idf_val
        return vec

    @staticmethod
    def _cosine_sim(a: dict[str, float], b: dict[str, float]) -> float:
        """余弦相似度"""
        if not a or not b:
            return 0.0

        dot = 0.0
        for k in a:
            if k in b:
                dot += a[k] * b[k]

        norm_a = math.sqrt(sum(v * v for v in a.values()))
        norm_b = math.sqrt(sum(v * v for v in b.values()))

        if norm_a * norm_b == 0:
            return 0.0

        return dot / (norm_a * norm_b)
