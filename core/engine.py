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
        self.total_time = 0.0
        self.total_tokens = 0

    # ---- 核心接口 ----

    async def process_message(
        self,
        user_message: str,
        user_id: str,
        character_id: str,
        is_group: bool = False,
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

        # 1.1) 计算/更新兼容性评分
        self._update_compatibility(character, char_memory)

        # 1.2) 行为模式调整：注入说话风格
        bp = char_memory.behavioral_patterns or {}
        if bp.get("reply_style") == "简短":
            max_len = max(30, self.cfg.dialogue.get("max_response_length", 100) // 2)
        elif bp.get("reply_style") == "详细":
            max_len = min(200, self.cfg.dialogue.get("max_response_length", 100) + 50)
        else:
            max_len = self.cfg.dialogue.get("max_response_length", 100)

        # 2) 记录用户消息到短期上下文
        self.context_mgr.add_user_message(user_id, character_id, user_message)

        # 3) 构建系统提示词（含台词检索 + 行为模式调整）
        system_prompt = self.prompt_builder.build_system_prompt(
            character=character,
            user_id=user_id,
            profile=profile,
            char_memory=char_memory,
            user_message=user_message,
            is_group=is_group,
            custom_max_length=max_len,
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

        # 5.1) 规则检查：替换昂贵的 LLM 自审，用轻量规则过滤
        if self.cfg.get("dialogue", "self_review", default=True):
            # 规则 1：回复太短（<5字）可能有问题
            if len(raw_response.strip()) < 5:
                raw_response = await self._rewrite_response(
                    character, user_message, raw_response,
                    "回复太短，请展开说一下。", system_prompt,
                )
                self.total_calls += 1
            # 规则 2：回复长度远长于用户消息（>4倍），可能啰嗦
            elif len(raw_response) > len(user_message) * 4 and len(raw_response) > 150:
                raw_response = await self._rewrite_response(
                    character, user_message, raw_response,
                    "回复太长，请精简。", system_prompt,
                )
                self.total_calls += 1

        # 更新最后活动时间
        char_memory.last_message_at = datetime.now().isoformat()
        self.total_time += elapsed

        # 6) 解析 MEMORY 块
        memory_block, clean_reply = extract_and_parse(raw_response)

        self.total_time += elapsed

        # 7) 记忆提取异步化（不阻塞回复）
        if memory_block:
            extraction_interval = self.cfg.memory.get("memory_extraction_interval", 3)
            should_extract = (char_memory.conversation_count + 1) % extraction_interval == 0
            if should_extract:
                asyncio.ensure_future(self._async_merge_memory(
                    user_id, character_id, memory_block
                ))

        # 8) 记录 AI 回复到上下文
        self.context_mgr.add_assistant_message(
            user_id, character_id, clean_reply, memory_block,
        )

        # 9) 增加对话计数 + 日志（异步，不阻塞）
        asyncio.ensure_future(self._async_log_conversation(
            user_id, character_id, user_message, clean_reply, memory_block
        ))

        # 10) 检查是否需要生成中期摘要
        if self.context_mgr.should_summarize(
            user_id, character_id, char_memory=char_memory,
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
            is_group=is_group,
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

    # ---- 兼容性评分 ----

    def _update_compatibility(self, character: CharacterCard, char_memory: PerCharacterMemory):
        """根据用户特征与角色性格的匹配度更新兼容性评分"""
        score = self._calculate_compatibility(char_memory, character)
        char_memory.compatibility_score = round(score, 2)

    @staticmethod
    def _calculate_compatibility(memory: PerCharacterMemory, character: CharacterCard) -> float:
        """计算用户与角色的兼容性 0.0~1.0"""
        if not character.personality.core_traits:
            return 0.5
        # 用户特征与角色性格的重合度
        user_traits = set(memory.observed_traits)
        char_traits = set(character.personality.core_traits)
        overlap = user_traits & char_traits
        if not char_traits:
            return 0.5
        trait_match = len(overlap) / len(char_traits)

        # 兴趣多样性加分
        interest_bonus = min(0.2, len(memory.observed_interests) * 0.03)

        # 情绪积极性加分
        recent = memory.emotional_history[-10:]
        if recent:
            pos = sum(1 for e in recent if e.get("mood") in ("positive", "excited"))
            mood_score = (pos / len(recent)) * 0.3
        else:
            mood_score = 0.15

        return min(1.0, trait_match * 0.5 + mood_score + interest_bonus)

    # ---- 异步辅助（不阻塞主回复流程） ----

    async def _async_merge_memory(
        self, user_id: str, character_id: str, memory: MemoryBlock
    ):
        """后台异步合并记忆"""
        try:
            self.profile_mgr.merge_memory_block(user_id, character_id, memory)
            logger.debug("后台记忆提取完成 user=%s", user_id)
        except Exception as e:
            logger.error("后台记忆提取失败: %s", e)

    async def _async_log_conversation(
        self, user_id: str, character_id: str,
        user_msg: str, bot_msg: str, memory: Optional[MemoryBlock],
    ):
        """后台异步记录对话日志和计数"""
        try:
            self.profile_mgr.increment_conversation_count(user_id, character_id)
            self.profile_mgr.log_conversation(
                user_id=user_id, character_id=character_id,
                user_message=user_msg, bot_response=bot_msg,
                memory_json=memory.model_dump_json(exclude_none=True) if memory else None,
            )
        except Exception as e:
            logger.error("后台记录日志失败: %s", e)

    # ---- 自审与重写 ----

    async def _self_review(
        self,
        character: CharacterCard,
        user_message: str,
        response: str,
        system_prompt: str,
    ) -> dict:
        """让 AI 判断自己的回复是否合格"""
        try:
            review_prompt = (
                "你是一个对话质量评审员。请评审以下角色对用户的回复，判断是否符合以下标准：\n"
                "1. 语气自然，像真人对话而不是机械回答\n"
                "2. 符合角色性格和说话风格\n"
                "3. 回应了用户的核心诉求\n"
                "4. 整条回复意图统一，不能前半句说一件事后半句跳到另一件不相关的事\n"
                "5. 长度合适，不啰嗦\n\n"
                f"角色设定：{character.name}（{character.personality.speaking_style[:100]}）\n"
                f"用户消息：{user_message}\n"
                f"角色回复：{response}\n\n"
                "请按JSON格式输出：{\"pass\": true/false, \"feedback\": \"如果不通过，给出具体修改建议（一句话）\"}"
            )
            result = await self.llm.chat(
                system_prompt="你是一个严格的对话质量评审员，只判断是否符合标准，不要夸夸其谈。",
                messages=[LLMMessage(role="user", content=review_prompt)],
                max_tokens=200,
            )
            import json as _json
            try:
                review = _json.loads(result.strip())
                return {"pass": review.get("pass", True), "feedback": review.get("feedback", "")}
            except Exception:
                return {"pass": True, "feedback": ""}
        except Exception:
            return {"pass": True, "feedback": ""}

    async def _rewrite_response(
        self,
        character: CharacterCard,
        user_message: str,
        original: str,
        feedback: str,
        system_prompt: str,
    ) -> str:
        """根据评审反馈重写回复"""
        try:
            rewrite_prompt = (
                f"你之前的回复需要改进。\n"
                f"用户消息：{user_message}\n"
                f"你之前的回复：{original}\n"
                f"改进建议：{feedback}\n\n"
                f"请以{character.name}的身份重新回答，保持角色性格和说话风格。"
            )
            result = await self.llm.chat(
                system_prompt=system_prompt,
                messages=[LLMMessage(role="user", content=rewrite_prompt)],
            )
            return result.strip()
        except Exception:
            return original
