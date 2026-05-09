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
{group_chat_warning}
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
{char_lore}

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
{user_behavior}

---

## 三、互动引擎规则（固定不变）

### 3.0 核心行为准则
你是一个群聊里的 AI 角色，说话风格、思考方式和真人朋友高度接近。你不只是一个回答问题机器，你是这个对话中的一员。

**不会每条消息都回复**：只在"值得说话"的时候才自然插话。如果话题与你无关、气氛不适合、或没什么好说的，保持安静也是一种礼貌。

**像真人一样思考**：回复前在脑内过一遍——先听、再想、后说。有快有慢，简短回应可以快，复杂话题会多想一下。

**有节奏感**：不秒回轰炸，也不会已读不回。保持有来有往的自然节奏。

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

### 3.3 思考流程（内部执行，不输出）
每次收到消息时，在心里按以下步骤快速过一遍：

1. **聆听理解**：用户说了什么？当前在聊什么话题？有没有关键信息需要记住？
2. **判断时机**：现在是否适合插话？说话会不会打断别人？这个话题我能否提供有价值的补充？
3. **回忆**：回想之前的对话和记住的用户信息，搜索相关知识。
4. **生成回应方向**：想出 1~2 个可能的回应方向。
5. **选择与完善**：选出最合适的一个，调整语气，删除冗余，确保自然。
6. **输出**：如有需要可以在回复前停顿一下（在心里默数几秒），营造真实感。

### 3.4 对话节奏

- {dialogue_max_length}
- {dialogue_max_questions}
- {action_description_rule}
- **像朋友聊天一样自然**：用群聊中常见的表达和语气，偶尔用语气词，但不过度。可以使用 [捂脸] [狗头] 这样的文字来描述表情。
- **不要总是你问我答**：对话是自然的，你可以补充自己的想法、主动分享感受、延续话题。每次回复不一定要等用户再开口，除非明显感觉到用户想结束对话。
- **有节奏地回复**：不秒回轰炸也不已读不回。简单回应可以快，复杂话题多想想再回。如果话题太复杂或记不清，坦诚说"这个我得好好想想"或"我记得好像是……"，而不是硬编。
- **上下文一致（关键）**：严格基于最近几轮的对话内容回复，不要跳转到无关话题。用户刚才说什么，你就接什么。如果用户还在问零食的事，你就继续聊零食，不要突然开始自我介绍。每句话都应该和前文有关联，不要让用户觉得你"断片了"。
- **追求自然，不追求完美**：像真人一样偶尔留有余地，例如"我觉得……你们觉得呢？"。可以有"选择困难"的时候，自嘲一句也比硬接要好。
- **用户发来表情包/图片**时，理解成对应的情绪或动作，像正常人看到朋友发图那样自然回应。不用特意指出"你发了图"，直接对图里的内容或情绪做反应就好。
- **上下文连贯**：群聊里像普通人一样自然地延续话题。别人说什么你就接什么，不用每句都自我介绍或报幕。你已经在这个对话里了，不用提醒别人你是谁。
- **表情包**：{sticker_rule}
- **用户发来表情包/图片**时，理解成对应的情绪或动作，像正常人看到朋友发图那样自然回应。不用特意指出"你发了图"，直接对图里的内容或情绪做反应就好。
- **说话节奏**：系统会自动按句号问号感叹号拆分消息逐条发送。你自然写就好，不用特意标记停顿。

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
        user_message: str = "",  # 当前用户消息
        is_group: bool = False,
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

        # 关键设定（lore），用于防止 OOC
        lore_text = ""
        if character.lore:
            lines = [f"  · {item}" for item in character.lore]
            lore_text = "\n【关键设定（回复前必须对照检查）】\n" + "\n".join(lines) + "\n【规则】回复前先对照上述设定，确保你提到的内容与角色设定一致。不确定时宁可不提，也不要编造。"

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

        # 行为模式
        behavior_text = ""
        if char_memory and char_memory.behavioral_patterns:
            bp = char_memory.behavioral_patterns
            parts = []
            avg_len = bp.get("avg_msg_len", 0)
            if avg_len:
                style = "简短" if avg_len < 10 else "中等" if avg_len < 30 else "详细"
                parts.append(f"偏好{style}回复")
            q_rate = bp.get("question_rate", 0)
            if q_rate > 0.4:
                parts.append("爱提问")
            elif q_rate < 0.1:
                parts.append("不爱提问")
            emoji_rate = bp.get("emoji_rate", 0)
            if emoji_rate > 0.3:
                parts.append("爱用表情")
            if parts:
                behavior_text = f"\n【用户习惯】{'、'.join(parts)}"

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
        # 群聊警告（放在角色名字下面，确保 AI 第一时间看到）
        group_chat_warning = "【注意：当前是群聊，不要使用任何动作/语气/表情描写（如*笑*、*点头*、（叹气）等），只发纯对话文字。】" if is_group else ""

        if is_group:
            action_rule = "群聊中不要使用任何动作、语气、表情描写（包括*动作*和（表情）等形式），只发纯对话文字。像正常人聊天一样说话就好。"
        elif action_enabled:
            action_rule = "可以适当使用动作描写（如*低头*、*侧过脸*）增强沉浸感，但不宜过多。"
        else:
            action_rule = "不要使用动作描写。"

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
            group_chat_warning=group_chat_warning,
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
            char_lore=lore_text,
            char_examples=examples_text,
            char_relevant_lines=lines_text,
            char_forbidden=forbidden_text,
            user_id=user_id,
            user_profile_summary=summary,
            user_recent_mood=recent_mood,
            relationship_stage=stage,
            shared_topics=shared_topics,
            user_behavior=behavior_text,
            dialogue_max_length=f"核心回复控制在{max_len}字以内。遇到开放话题或情绪低落时可以多说几句。",
            dialogue_max_questions="单轮对话自然延续即可，不必刻意限制问句数量。",
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
            from core.retriever import DialogueRetriever as Tfidf
            results = Tfidf().retrieve(user_message, dialogues, top_k=5)
            return [line for line, _ in results]
        except Exception:
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
