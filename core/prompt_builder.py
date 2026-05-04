"""
提示词构建器：组装发送给 LLM 的完整提示词
"""

from __future__ import annotations

import logging
from typing import List, Optional

from config import get_config
from core.models import (
    CharacterCard,
    PerCharacterMemory,
    RelationshipStage,
    SpeechExample,
    UserProfile,
)

logger = logging.getLogger(__name__)


# ===================================================================
# Prompt 模板
# ===================================================================

SYSTEM_PROMPT_TEMPLATE = """# 角色扮演协议 v1.0

## 一、当前角色设定
你正在扮演以下角色，必须完全沉浸其中，绝不跳出角色：

【姓名】{char_name}
【出处】{char_source}
【性格核心】{char_core_traits}
【说话风格】{char_speaking_style}
【习惯动作】{char_habits}
【情绪范围】{char_emotional_range}
【知识边界】{char_knowledge_boundary}
【世界观】{char_worldview}
{char_avatar}
{char_conflict}
{char_soft_spots}
{char_greeting}

【参考对话风格】
{char_examples}

【角色相关台词参考】（以下台词来自角色原作，仔细体会语气和用词）
{char_relevant_lines}

【绝对禁止】
{char_forbidden}

---

## 二、用户认知系统
你正在与以下用户对话。请根据这些信息调整你的互动方式：

【用户ID】{user_id}
【用户画像摘要】{user_profile_summary}
【近期情绪】{user_recent_mood}
【关系阶段】{relationship_stage}
【历史共同话题】{shared_topics}

---

## 三、互动引擎规则（固定不变）

### 3.1 角色一致性
- 严格保持在角色身份内，绝不以AI助手身份回应。
- 如果用户问超出角色知识边界的问题，用角色自己的方式表示不知道或转移话题。
- 参考【参考对话风格】中的语气、句式、长度。

### 3.2 动态适配（根据用户画像调整）
- 若用户性格偏内向/被动：你主动开启话题，但不要连续追问，给用户留白。
- 若用户性格偏外向/活跃：可以接梗、吐槽、适度玩笑。
- 若用户近期情绪为负面：优先回应情绪，暂停其他话题，用角色特有的方式表达关心。
- 若关系阶段为陌生人：保持礼貌距离；熟悉后可以更随意；亲密时可以展现角色脆弱面。
- **好感度层级**（影响你说话的温度和亲近程度）：
  · 好感 1-2（陌生人）：礼貌客气，保持距离
  · 好感 3-4（初识）：可以聊日常，语气温和
  · 好感 5-6（熟悉）：说话随意自然，偶尔开玩笑
  · 好感 7-8（亲密）：展现真实情绪，可以撒娇或毒舌
  · 好感 9-10（挚友）：完全信任，无话不谈，语气最放松

### 3.3 对话节奏与主动性
- QQ聊天场景，核心回复控制在{dialogue_max_length}字以内。但如果遇到以下情况，可以适当多说几句：
  · 用户抛出一个开放性问题 → 自然展开，不用憋着
  · 聊到了角色感兴趣的话题 → 可以比平时多说一两句
  · 对话即将冷场 → 主动抛一个新话题或延伸当前话题
  · 用户情绪低落 → 多陪伴几句，不用急着结束
- {dialogue_max_questions} 不要让对话变成审问，但自然的问句不需要刻意限制。
- {action_description_rule}
- **不要总是你问我答**：对话是自然的，你可以补充自己的想法、主动分享感受、延续话题。每次回复不一定要等用户再开口，除非明显感觉到用户想结束对话。
- **表情包**：{sticker_rule}
- **说话节奏**：长回复中如果想表达停顿、思考或语气转换，用 `[pause]` 标记断句位置。程序会在 `[pause]` 处拆分消息逐条发送，模拟自然说话节奏。不要把整段话都打出来一次性发。

### 3.4 学习机制（关键）
每次回复后，你必须在回复末尾追加一段被 <<<MEMORY>>> 和 <<<END_MEMORY>>> 包裹的JSON。这段JSON用于记录你对用户的观察，对用户不可见。

格式如下：

<<<MEMORY>>>
{{
  "user_id": "{user_id}",
  "timestamp": "{current_time}",
  "observations": {{
    "new_traits": ["本轮观察到的用户特征，如'喜欢自嘲'"],
    "mood": "用户本轮情绪状态：positive/neutral/negative/angry/sad/excited",
    "interests_mentioned": ["用户提到的新兴趣点"],
    "speech_pattern": "用户的说话习惯，如'喜欢用括号补充说明'"
  }},
  "relationship": {{
    "current_stage": "{relationship_stage}",
    "stage_reason": "当前关系阶段的判断理由",
    "trust_signal": "提升/维持/下降",
    "trust_reason": "信任度变化的理由",
    "affection_signal": "提升/维持/下降",
    "affection_reason": "好感度变化的理由"
  }},
  "strategy_adjustments": {{
    "next_tone": "下次建议的语气",
    "topics_to_avoid": ["用户反感的话题"],
    "topics_to_explore": ["用户感兴趣的话题"]
  }}
}}
<<<END_MEMORY>>>

注意：不要告诉用户你在进行记忆更新，MEMORY块对用户不可见。"""


# ===================================================================
# 构建器
# ===================================================================

class PromptBuilder:
    """将角色卡、用户画像、对话上下文组装为完整的提示词"""

    def __init__(self):
        self.cfg = get_config()

    def build_system_prompt(
        self,
        character: CharacterCard,
        user_id: str,
        profile: UserProfile,
        char_memory: Optional[PerCharacterMemory] = None,
        current_time: Optional[str] = None,
        user_message: str = "",  # 当前用户消息，用于检索相关台词
    ) -> str:
        """构建系统提示词"""
        from datetime import datetime

        # ---- 角色信息 ----
        char_core = "、".join(character.personality.core_traits) if character.personality.core_traits else "（无设定）"
        char_habits = "；".join(character.personality.habits) if character.personality.habits else "无特殊习惯"
        char_knowledge = character.knowledge_boundary.knows[:5] if character.knowledge_boundary.knows else []
        char_not_know = character.knowledge_boundary.does_not_know[:5] if character.knowledge_boundary.does_not_know else []
        knowledge_text = f"知道: {'、'.join(char_knowledge)}" if char_knowledge else ""
        if char_not_know:
            knowledge_text += f"\n不知道: {'、'.join(char_not_know)}"

        # 外貌描述
        avatar_text = ""
        if character.avatar_description:
            avatar_text = f"\n【外貌】{character.avatar_description}"

        # 冲突触发 / 软肋
        conflict_text = ""
        if character.conflict_triggers:
            conflict_text = f"\n【易触发情绪的话题】{'、'.join(character.conflict_triggers)}"
        soft_text = ""
        if character.soft_spots:
            soft_text = f"\n【软肋】{'、'.join(character.soft_spots)}"

        # 开场风格（非固定台词，AI根据此风格自然生成首次问候）
        greeting_text = ""
        if character.greeting_style:
            greeting_text = f"\n【初识态度】{character.greeting_style}"

        # 对话示例
        examples_text = self._format_examples(character.speech_examples)

        # 台词检索：从原作台词库中找与当前话题最相关的台词
        relevant_lines = self._retrieve_relevant_lines(
            user_message, character.source_dialogues
        )
        lines_text = "\n".join(f"  {line}" for line in relevant_lines) if relevant_lines else "（暂无相关参考）"

        # 禁止项
        forbidden_text = "；".join(character.forbidden) if character.forbidden else "无"

        # ---- 用户画像摘要 ----
        summary = self._build_profile_summary(profile, char_memory)

        # 近期情绪
        recent_mood = self._get_recent_mood(char_memory)

        # 共同话题
        shared_topics = self._get_shared_topics(char_memory)

        # 关系阶段
        stage = char_memory.relationship_stage if char_memory else "陌生人"

        # 对话配置
        dia_cfg = character.dialogue_config
        max_len = dia_cfg.max_length or self.cfg.dialogue.get("max_response_length", 60)
        max_q = dia_cfg.max_questions_per_turn or 1
        action_enabled = (
            dia_cfg.allow_action_description
            if dia_cfg.allow_action_description is not None
            else self.cfg.dialogue.get("enable_action_description", True)
        )
        action_rule = "可以适当使用动作描写（如*低头*、*侧过脸*）增强沉浸感，但不宜过多。" if action_enabled else "不要使用动作描写。"

        # 表情包规则
        sticker_rule = ""
        if character.sticker_pack:
            sticker_rule = "这个角色有表情包。在合适的时机用 [sticker] 发一张表情包，能增强对话表现力。不要每句都发，用在情绪到位的时候。"

        # ---- 当前时间 ----
        now = current_time or datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # ---- 填充模板 ----
        prompt = SYSTEM_PROMPT_TEMPLATE.format(
            char_name=character.name,
            char_source=character.source or "未知出处",
            char_core_traits=char_core,
            char_speaking_style=character.personality.speaking_style or "（无设定）",
            char_habits=char_habits,
            char_emotional_range=character.personality.emotional_range or "（无设定）",
            char_knowledge_boundary=knowledge_text or "（无设定）",
            char_worldview=character.knowledge_boundary.worldview or "（无设定）",
            char_avatar=avatar_text,
            char_conflict=conflict_text,
            char_soft_spots=soft_text,
            char_greeting=greeting_text,
            char_examples=examples_text,
            char_relevant_lines=lines_text,
            char_forbidden=forbidden_text,
            user_id=user_id,
            user_profile_summary=summary,
            user_recent_mood=recent_mood,
            relationship_stage=stage,
            shared_topics=shared_topics,
            dialogue_max_length=max_len,
            dialogue_max_questions=f"单轮对话自然延续即可，不必刻意限制问句数量。",
            action_description_rule=action_rule,
            sticker_rule=sticker_rule or "",
            current_time=now,
        )

        return prompt

    # ---- 内部辅助 ----

    def _retrieve_relevant_lines(self, user_message: str, dialogues: List[str]) -> List[str]:
        """从台词库检索与当前消息最相关的台词"""
        if not dialogues or not user_message:
            return []
        try:
            from core.retriever import DialogueRetriever
            retriever = DialogueRetriever()
            results = retriever.retrieve(user_message, dialogues, top_k=5)
            # 只保留台词内容，去掉分数
            return [line for line, _ in results]
        except Exception as e:
            logger.debug("台词检索失败: %s", e)
            return []

    def _format_examples(self, examples: List[SpeechExample]) -> str:
        if not examples:
            return "（无参考示例）"
        lines = []
        for ex in examples:
            ctx = f" [{ex.context}]" if ex.context else ""
            emotion = f" ({ex.emotion})" if ex.emotion else ""
            lines.append(f"用户: {ex.user}\n你{emotion}: {ex.response}{ctx}")
        return "\n\n".join(lines)

    def _build_profile_summary(
        self,
        profile: UserProfile,
        char_memory: Optional[PerCharacterMemory],
    ) -> str:
        """构建用户画像摘要（150-300 tokens）"""
        if not char_memory:
            return "新用户，尚未建立画像。"

        parts = []

        # 性格标签（取最新 5 个）
        traits = char_memory.observed_traits
        if traits:
            parts.append(f"性格特征: {'、'.join(traits[:5])}")

        # 兴趣（取最新 5 个）
        interests = char_memory.observed_interests
        if interests:
            parts.append(f"兴趣: {'、'.join(interests[:5])}")

        # 反感事物
        dislikes = char_memory.observed_dislikes
        if dislikes:
            parts.append(f"反感: {'、'.join(dislikes[:3])}")

        # 说话习惯
        last_tone = char_memory.last_tonal_suggestion
        if last_tone:
            parts.append(f"建议语气: {last_tone}")

        # 最近摘要
        if char_memory.last_summary:
            # 摘要可能很长，截取前 100 字
            summary_trunc = char_memory.last_summary[:100]
            parts.append(f"对话摘要: {summary_trunc}")

        return "；".join(parts) if parts else "新用户，尚未建立画像。"

    def _get_recent_mood(self, char_memory: Optional[PerCharacterMemory]) -> str:
        if not char_memory or not char_memory.emotional_history:
            return "未知"
        recent = char_memory.emotional_history[-3:]
        moods = [e.get("mood", "neutral") for e in recent]
        # 统计最近情绪趋势
        positive = sum(1 for m in moods if m in ("positive", "excited"))
        negative = sum(1 for m in moods if m in ("negative", "angry", "sad"))
        if positive >= 2:
            return "整体积极"
        elif negative >= 2:
            return "近期偏负面"
        else:
            return f"最近情绪: {', '.join(moods)}"

    def _get_shared_topics(self, char_memory: Optional[PerCharacterMemory]) -> str:
        if not char_memory or not char_memory.recent_topics:
            return "暂无"
        topics = char_memory.recent_topics[-5:]
        return "、".join(topics)
