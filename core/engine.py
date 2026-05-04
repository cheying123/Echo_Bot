"""
核心引擎：对话编排与执行的主逻辑

流程：
  用户消息 → 构建 Prompt → 调用 LLM → 解析响应
  → 更新用户档案 → 管理上下文窗口 → 返回回复文本
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from datetime import datetime
from typing import AsyncGenerator, Optional, Tuple

from config import get_config
from core.character_manager import CharacterManager
from core.context_manager import ContextManager
from core.llm_client import LLMClient, LLMMessage, create_llm_client
from core.memory_parser import extract_and_parse
from core.models import (
    CharacterCard,
    MemoryBlock,
    MemoryObservation,
    PerCharacterMemory,
    RelationshipState,
    StrategyAdjustment,
    UserProfile,
)
from core.profile_manager import ProfileManager
from core.prompt_builder import PromptBuilder

logger = logging.getLogger(__name__)

# 风格兜底回复池
_FALLBACK_REPLIES: dict[str, list[str]] = {
    "布偶熊": [
        "嗯……*打了个哈欠* 刚才走神了一下，你说到哪了？",
        "*揉了揉眼睛* 啊～刚才系统卡了一下，你再说一遍？",
        "啧……等我缓一下。*戳了戳耳机* 这破网络。",
    ],
    "露西亚": [
        "抱歉，刚才信号不太好。你说了什么？",
        "（微微愣神）……我在听。能再说一次吗？",
        "通讯出了一点小问题。你还好吗？",
    ],
    "林黛玉": [
        "（轻咳一声）方才走了神，你再说一遍可好？",
        "……一时没听清，劳你再说一句。",
        "这话被风截了去，我没听真切。",
    ],
    "绫波丽": [
        "……没听清。再说一次。",
        "……通讯中断了一下。继续。",
        "……嗯？信号不好。",
    ],
}

_FALLBACK_GENERIC = [
    "嗯？刚才有点走神，能再说一遍吗？",
    "（信号不稳定）抱歉，没听清。",
    "稍等，我理一下思路。你刚才说什么来着？",
]


class DialogueEngine:
    """
    对话引擎主类
    """

    def __init__(
        self,
        character_manager: CharacterManager,
        profile_manager: ProfileManager,
        llm_client: Optional[LLMClient] = None,
    ):
        self.cfg = get_config()
        self.char_mgr = character_manager
        self.profile_mgr = profile_manager
        self.llm = llm_client or create_llm_client()
        self.prompt_builder = PromptBuilder()
        self.context_mgr = ContextManager(
            max_short_term_rounds=self.cfg.memory.get("short_term_rounds", 8),
        )

        # 运行时统计
        self.total_calls = 0
        self.total_errors = 0

    # ---- 核心接口 ----

    async def process_message(
        self,
        user_message: str,
        user_id: str,
        character_id: str,
    ) -> Tuple[str, Optional[dict]]:
        """
        处理一条用户消息，返回 (AI回复文本, MEMORY数据或None)
        """
        character = self.char_mgr.get_character(character_id)
        if not character:
            raise ValueError(f"角色不存在: {character_id}")

        # 1) 获取用户档案
        profile = self.profile_mgr.get_or_create_profile(user_id)
        char_memory = profile.get_or_create_char_memory(character_id)

        # 2) 记录用户消息到短期上下文
        self.context_mgr.add_user_message(user_id, character_id, user_message)

        # 3) 构建系统提示词（含台词检索）
        system_prompt = self.prompt_builder.build_system_prompt(
            character=character,
            user_id=user_id,
            profile=profile,
            char_memory=char_memory,
            user_message=user_message,
        )

        # 4) 获取最近对话历史
        history = self.context_mgr.get_clean_history(user_id, character_id)
        messages = [LLMMessage(**h) for h in history]

        # 5) 调用 LLM
        self.total_calls += 1
        start_time = time.time()

        try:
            raw_response = await self.llm.chat(
                system_prompt=system_prompt,
                messages=messages,
            )
        except Exception as e:
            self.total_errors += 1
            logger.error("LLM 调用失败 user=%s char=%s: %s", user_id, character_id, e)
            return self._fallback_reply(character, user_id, character_id, profile, char_memory)

        elapsed = time.time() - start_time
        logger.info(
            "LLM 响应 user=%s char=%s len=%d time=%.1fs",
            user_id, character_id, len(raw_response), elapsed,
        )

        # 6) 解析 MEMORY 块
        memory_block, clean_reply = extract_and_parse(raw_response)

        # 7) 按间隔控制记忆提取
        extraction_interval = self.cfg.memory.get("memory_extraction_interval", 3)
        should_extract = (
            memory_block is not None
            and (char_memory.conversation_count + 1) % extraction_interval == 0
        )

        if memory_block and should_extract:
            self.profile_mgr.merge_memory_block(user_id, character_id, memory_block)
            logger.debug("MEMORY 提取 user=%s mood=%s", user_id, memory_block.observations.mood)
        elif memory_block:
            logger.debug("跳过本轮记忆提取（interval=%d）", extraction_interval)

        # 8) 记录 AI 回复到上下文
        self.context_mgr.add_assistant_message(
            user_id, character_id, clean_reply, memory_block,
        )

        # 9) 增加对话计数
        self.profile_mgr.increment_conversation_count(user_id, character_id)

        # 10) 记录对话日志
        self.profile_mgr.log_conversation(
            user_id=user_id,
            character_id=character_id,
            user_message=user_message,
            bot_response=clean_reply,
            memory_json=memory_block.model_dump_json(exclude_none=True) if memory_block else None,
        )

        # 11) 检查是否需要生成中期摘要
        if self.context_mgr.should_summarize(
            user_id, character_id,
            interval=self.cfg.memory.get("summary_interval", 10),
        ):
            asyncio.ensure_future(
                self._generate_summary(user_id, character_id, profile)
            )

        return clean_reply, memory_block.model_dump() if memory_block else None

    async def process_message_stream(
        self,
        user_message: str,
        user_id: str,
        character_id: str,
    ) -> AsyncGenerator[str, None]:
        """流式处理用户消息（预留）"""
        character = self.char_mgr.get_character(character_id)
        if not character:
            raise ValueError(f"角色不存在: {character_id}")

        profile = self.profile_mgr.get_or_create_profile(user_id)
        char_memory = profile.get_or_create_char_memory(character_id)

        self.context_mgr.add_user_message(user_id, character_id, user_message)

        system_prompt = self.prompt_builder.build_system_prompt(
            character=character,
            user_id=user_id,
            profile=profile,
            char_memory=char_memory,
            user_message=user_message,
        )

        history = self.context_mgr.get_clean_history(user_id, character_id)
        messages = [LLMMessage(**h) for h in history]

        full_response = ""
        try:
            async for chunk in self.llm.chat_stream(
                system_prompt=system_prompt,
                messages=messages,
            ):
                full_response += chunk
                yield chunk
        except Exception as e:
            self.total_errors += 1
            fbk, _ = self._fallback_reply(character, user_id, character_id, profile, char_memory)
            yield fbk
            return

        memory_block, clean_reply = extract_and_parse(full_response)
        if memory_block:
            extraction_interval = self.cfg.memory.get("memory_extraction_interval", 3)
            if (char_memory.conversation_count + 1) % extraction_interval == 0:
                self.profile_mgr.merge_memory_block(user_id, character_id, memory_block)

        self.context_mgr.add_assistant_message(
            user_id, character_id, clean_reply, memory_block,
        )
        self.profile_mgr.increment_conversation_count(user_id, character_id)
        self.total_calls += 1

    # ---- 兜底回复 ----

    def _fallback_reply(
        self,
        character: CharacterCard,
        user_id: str,
        character_id: str,
        profile: UserProfile,
        char_memory: PerCharacterMemory,
    ) -> Tuple[str, Optional[dict]]:
        """LLM 调用失败时返回角色风格的兜底回复"""
        name = character.name
        pool = _FALLBACK_REPLIES.get(name, _FALLBACK_GENERIC)
        reply = random.choice(pool)

        # 同时生成一个平和的 MEMORY 块，保持数据连贯
        memory = MemoryBlock(
            user_id=user_id,
            timestamp=datetime.now().isoformat(),
            observations=MemoryObservation(
                mood="neutral",
            ),
            relationship=RelationshipState(
                current_stage=char_memory.relationship_stage or "陌生人",
                trust_signal="维持",
                affection_signal="维持",
            ),
            strategy_adjustments=StrategyAdjustment(
                next_tone="保持自然",
            ),
        )

        self.context_mgr.add_assistant_message(user_id, character_id, reply, memory)

        logger.info("返回兜底回复 user=%s char=%s", user_id, character_id)
        return reply, None

    # ---- 摘要生成 ----

    async def _generate_summary(self, user_id: str, character_id: str, profile: UserProfile):
        """生成中期对话摘要（背景任务）"""
        try:
            turns = self.context_mgr.get_recent_turns(user_id, character_id, 20)
            if not turns:
                return

            dialogue_text = "\n".join(
                f"{'用户' if t.role == 'user' else '你'}: {t.content[:200]}"
                for t in turns[-10:]
            )

            summary_prompt = (
                "请总结以下对话的主要内容，包括：\n"
                "1. 用户的核心诉求或兴趣点\n"
                "2. 对话中涉及的主要话题\n"
                "3. 用户展现出的性格特征\n"
                "4. 关系进展\n"
                "控制在 200 字以内。\n\n"
                f"对话记录：\n{dialogue_text}"
            )

            summary = await self.llm.chat(
                system_prompt="你是对话分析助手，请简洁总结对话。",
                messages=[LLMMessage(role="user", content=summary_prompt)],
                max_tokens=300,
            )

            self.profile_mgr.update_summary(user_id, character_id, summary)
            logger.info("生成对话摘要成功 user=%s char=%s", user_id, character_id)

        except Exception as e:
            logger.error("生成摘要失败: %s", e)
