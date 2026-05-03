"""
对话上下文管理器

管理短期记忆窗口：按 (user_id, character_id) 维护独立的对话历史。
支持历史裁剪、摘要替换。
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple

from core.models import ConversationContext, ConversationTurn

logger = logging.getLogger(__name__)


class ContextManager:
    """
    对话上下文管理器

    以 (user_id, character_id) 为键，管理独立的对话历史窗口。
    线程安全（单线程 asyncio 场景下不需要锁）。
    """

    def __init__(self, max_short_term_rounds: int = 8):
        self._max_rounds = max_short_term_rounds
        # key: f"{user_id}:{character_id}" -> ConversationContext
        self._contexts: Dict[str, ConversationContext] = {}

    # ---- 公开方法 ----

    def get_or_create(self, user_id: str, character_id: str) -> ConversationContext:
        """获取或创建对话上下文"""
        key = self._key(user_id, character_id)
        if key not in self._contexts:
            self._contexts[key] = ConversationContext(
                user_id=user_id,
                character_id=character_id,
            )
        return self._contexts[key]

    def add_user_message(self, user_id: str, character_id: str, content: str):
        """添加用户消息"""
        ctx = self.get_or_create(user_id, character_id)
        ctx.add_turn("user", content)

    def add_assistant_message(
        self,
        user_id: str,
        character_id: str,
        content: str,
        memory_block=None,
    ):
        """添加 AI 回复"""
        ctx = self.get_or_create(user_id, character_id)
        ctx.add_turn("assistant", content, memory_block)

    def get_clean_history(
        self,
        user_id: str,
        character_id: str,
        n: Optional[int] = None,
    ) -> List[dict]:
        """
        获取最近的对话历史（已剥离 MEMORY 块）

        Returns:
            [{"role": "user"/"assistant", "content": "..."}, ...]
        """
        ctx = self.get_or_create(user_id, character_id)
        n = n or self._max_rounds
        return ctx.get_clean_history(n)

    def get_recent_turns(
        self,
        user_id: str,
        character_id: str,
        n: Optional[int] = None,
    ) -> List[ConversationTurn]:
        """获取最近 N 轮原始对话（含 MEMORY 块）"""
        ctx = self.get_or_create(user_id, character_id)
        n = n or self._max_rounds
        return ctx.get_recent_turns(n)

    def get_conversation_count(self, user_id: str, character_id: str) -> int:
        """获取角色回复次数"""
        ctx = self.get_or_create(user_id, character_id)
        return ctx.character_turns

    def should_summarize(self, user_id: str, character_id: str, interval: int = 10) -> bool:
        """
        判断是否需要生成中期摘要。
        当角色回复次数达到 interval 的倍数时返回 True。
        """
        count = self.get_conversation_count(user_id, character_id)
        return count > 0 and count % interval == 0

    def clear_context(self, user_id: str, character_id: str):
        """清空某个对话的短期上下文"""
        key = self._key(user_id, character_id)
        self._contexts.pop(key, None)
        logger.info("清空对话上下文: %s", key)

    def get_all_active_sessions(self) -> List[Tuple[str, str]]:
        """获取所有活跃会话列表"""
        result = []
        for key in self._contexts:
            parts = key.split(":", 1)
            if len(parts) == 2:
                result.append((parts[0], parts[1]))
        return result

    def get_context_size(self, user_id: str, character_id: str) -> int:
        """获取当前上下文的总轮数"""
        ctx = self.get_or_create(user_id, character_id)
        return ctx.total_turns

    # ---- 内部方法 ----

    @staticmethod
    def _key(user_id: str, character_id: str) -> str:
        return f"{user_id}:{character_id}"
