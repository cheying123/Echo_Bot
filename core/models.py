"""
数据模型：角色卡、用户档案、MEMORY 数据结构
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ===================================================================
# 角色卡（Character Card）
# ===================================================================

class Personality(BaseModel):
    """角色性格"""
    core_traits: List[str] = Field(default_factory=list, description="性格标签")
    speaking_style: str = ""
    habits: List[str] = Field(default_factory=list)
    emotional_range: str = ""


class KnowledgeBoundary(BaseModel):
    """角色知识边界"""
    knows: List[str] = Field(default_factory=list)
    does_not_know: List[str] = Field(default_factory=list)
    worldview: str = ""


class SpeechExample(BaseModel):
    """对话示例"""
    user: str
    response: str
    context: Optional[str] = None
    emotion: Optional[str] = None


class DialogueConfig(BaseModel):
    """角色特定对话配置"""
    max_length: Optional[int] = None  # 覆盖全局设置
    allow_action_description: Optional[bool] = None
    max_questions_per_turn: Optional[int] = None


class CharacterCard(BaseModel):
    """完整的角色卡"""
    # 基础信息
    name: str
    source: str = ""
    version: str = "1.0"

    # 性格
    personality: Personality = Field(default_factory=Personality)

    # 知识边界
    knowledge_boundary: KnowledgeBoundary = Field(default_factory=KnowledgeBoundary)

    # 对话示例
    speech_examples: List[SpeechExample] = Field(default_factory=list)

    # 角色台词库（用于 RAG 检索，可放数百条原作台词）
    # 每条是一个字符串，可以是角色的单句台词或短对话
    source_dialogues: List[str] = Field(default_factory=list)

    # 限制
    forbidden: List[str] = Field(default_factory=list)
    forbidden_words: List[str] = Field(default_factory=list)

    # 扩展（可选）
    greeting_style: Optional[str] = None  # 角色与人初次接触时的态度风格，用于AI参考，非固定台词
    sticker_pack: List[str] = Field(default_factory=list)  # 表情包图片URL列表
    lore: List[str] = Field(default_factory=list)  # 关键设定事实，AI必须遵守，用于防止OOC
    avatar_description: Optional[str] = None  # 外貌描述
    relationship_with_user_default: str = "neutral"  # neutral | warm | cold | wary
    development_arc: Optional[str] = None  # 角色成长弧
    conflict_triggers: List[str] = Field(default_factory=list)  # 触发冲突的话题
    soft_spots: List[str] = Field(default_factory=list)  # 角色软肋
    dialogue_config: DialogueConfig = Field(default_factory=DialogueConfig)

    def validate_card(self) -> List[str]:
        """验证角色卡完整性，返回缺失字段列表"""
        missing = []
        if not self.name:
            missing.append("name")
        if not self.personality.core_traits:
            missing.append("personality.core_traits")
        if not self.personality.speaking_style:
            missing.append("personality.speaking_style")
        if not self.speech_examples:
            missing.append("speech_examples")
        return missing


# ===================================================================
# 关系阶段
# ===================================================================

class RelationshipStage(str, Enum):
    STRANGER = "陌生人"
    ACQUAINTED = "初识"
    FAMILIAR = "熟悉"
    CLOSE = "亲密"
    BEST_FRIEND = "挚友"


# 关系阶段数值映射（用于后端晋升逻辑）
STAGE_ORDER = [
    RelationshipStage.STRANGER,
    RelationshipStage.ACQUAINTED,
    RelationshipStage.FAMILIAR,
    RelationshipStage.CLOSE,
    RelationshipStage.BEST_FRIEND,
]


def stage_index(stage: RelationshipStage) -> int:
    return STAGE_ORDER.index(stage)


def promote_stage(current: RelationshipStage, levels: int = 1) -> RelationshipStage:
    idx = min(stage_index(current) + levels, len(STAGE_ORDER) - 1)
    return STAGE_ORDER[idx]


def demote_stage(current: RelationshipStage, levels: int = 1) -> RelationshipStage:
    idx = max(stage_index(current) - levels, 0)
    return STAGE_ORDER[idx]


# ===================================================================
# MEMORY 输出结构（AI 每轮输出的记忆块）
# ===================================================================

class MemoryObservation(BaseModel):
    """AI 输出的单轮观察"""
    new_traits: List[str] = Field(default_factory=list)
    mood: str = "neutral"  # positive | neutral | negative | angry | sad | excited
    interests_mentioned: List[str] = Field(default_factory=list)
    speech_pattern: str = ""

    def is_empty(self) -> bool:
        return (
            not self.new_traits
            and self.mood == "neutral"
            and not self.interests_mentioned
            and not self.speech_pattern
        )


class RelationshipState(BaseModel):
    """AI 建议的关系状态"""
    current_stage: str = "陌生人"
    stage_reason: str = ""
    trust_signal: str = "维持"  # 提升 | 维持 | 下降
    trust_reason: str = ""
    affection_signal: str = "维持"  # 提升 | 维持 | 下降
    affection_reason: str = ""


class StrategyAdjustment(BaseModel):
    """AI 建议的对话策略调整"""
    next_tone: str = ""
    topics_to_avoid: List[str] = Field(default_factory=list)
    topics_to_explore: List[str] = Field(default_factory=list)


class MemoryBlock(BaseModel):
    """完整 MEMORY 块"""
    user_id: str = ""
    timestamp: str = ""
    observations: MemoryObservation = Field(default_factory=MemoryObservation)
    relationship: RelationshipState = Field(default_factory=RelationshipState)
    strategy_adjustments: StrategyAdjustment = Field(default_factory=StrategyAdjustment)
    raw_json: str = ""  # 原始 JSON 字符串，用于调试


# ===================================================================
# 用户档案（User Profile）
# ===================================================================

class GlobalProfile(BaseModel):
    """全局用户画像（仅跨角色共享的元信息）"""
    language_preference: str = "zh"  # zh | zh-en-mix
    reply_length_preference: str = "normal"  # short | normal | long
    active_hours: List[str] = Field(default_factory=list)
    updated_at: str = ""


class PerCharacterMemory(BaseModel):
    """按角色存储的用户记忆"""
    relationship_stage: str = "陌生人"
    trust_level: int = 1
    affection_level: int = 1
    shared_history: List[str] = Field(default_factory=list)
    conversation_count: int = 0
    last_summary: str = ""
    summary_updated_at: str = ""
    # 累计的观察标签（由 MEMORY 聚合而来）
    observed_traits: List[str] = Field(default_factory=list)  # 性格特征标签
    observed_interests: List[str] = Field(default_factory=list)  # 兴趣标签
    observed_dislikes: List[str] = Field(default_factory=list)
    emotional_history: List[dict] = Field(default_factory=list)  # [{mood, timestamp}]
    recent_topics: List[str] = Field(default_factory=list)
    # 对话策略建议历史
    last_tonal_suggestion: str = ""
    # 最后活动时间（用于主动对话检测）
    last_message_at: str = ""
    # 遗忘追踪：标签最后出现时间
    trait_last_seen: Dict[str, str] = Field(default_factory=dict)  # trait -> timestamp
    # 行为模式分析
    behavioral_patterns: Dict[str, Any] = Field(default_factory=dict)  # 如 {"likes_questions": 0.7, "avg_msg_len": 12.3}
    # 兼容性评分（0.0-1.0，基于用户特征与角色性格的匹配度）
    compatibility_score: float = 0.0
    # 最近对话上下文（重启恢复用，最多 6 轮）
    recent_context: List[dict] = Field(default_factory=list)

    def compress(self, max_age_days: int = 30) -> bool:
        """压缩记忆：移除过时的特征标签，返回 True 表示有改动"""
        from datetime import datetime, timedelta
        now = datetime.now()
        cutoff = now - timedelta(days=max_age_days)
        changed = False

        # 过滤过时的性格标签
        kept_traits = []
        for t in self.observed_traits:
            last = self.trait_last_seen.get(t)
            if last:
                try:
                    if datetime.fromisoformat(last) < cutoff:
                        continue
                except Exception:
                    pass
            kept_traits.append(t)
        if len(kept_traits) != len(self.observed_traits):
            self.observed_traits = kept_traits
            changed = True

        # 限制情绪历史长度
        if len(self.emotional_history) > 50:
            self.emotional_history = self.emotional_history[-30:]
            changed = True

        return changed

    def mark_trait_seen(self, trait: str):
        """更新特征标签的最后出现时间"""
        from datetime import datetime
        self.trait_last_seen[trait] = datetime.now().isoformat()
    last_message_at: str = ""


class UserProfile(BaseModel):
    """完整用户档案"""
    user_id: str
    global_profile: GlobalProfile = Field(default_factory=GlobalProfile)
    per_character_memory: Dict[str, PerCharacterMemory] = Field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""

    def get_or_create_char_memory(self, character_id: str) -> PerCharacterMemory:
        if character_id not in self.per_character_memory:
            self.per_character_memory[character_id] = PerCharacterMemory()
        return self.per_character_memory[character_id]


# ===================================================================
# 对话上下文
# ===================================================================

class ConversationTurn(BaseModel):
    """一轮对话"""
    role: str  # "user" | "assistant"
    content: str
    timestamp: str = ""
    memory_block: Optional[MemoryBlock] = None  # assistant 回复可能带记忆


class ConversationContext(BaseModel):
    """对话上下文（短期记忆窗口）"""
    user_id: str
    character_id: str
    turns: List[ConversationTurn] = Field(default_factory=list)

    def add_turn(self, role: str, content: str, memory_block: Optional[MemoryBlock] = None):
        self.turns.append(ConversationTurn(
            role=role,
            content=content,
            timestamp=datetime.now().isoformat(),
            memory_block=memory_block,
        ))

    def get_recent_turns(self, n: int) -> List[ConversationTurn]:
        return self.turns[-n:]

    def get_clean_history(self, n: int) -> List[dict]:
        """获取历史对话（剥离 MEMORY 块），用于构建 prompt"""
        recent = self.get_recent_turns(n)
        return [
            {"role": t.role, "content": self._strip_memory(t.content)}
            for t in recent
        ]

    @staticmethod
    def _strip_memory(content: str) -> str:
        """剥离 MEMORY 标记"""
        import re
        return re.sub(
            r'<<<MEMORY>>>.*?<<<END_MEMORY>>>',
            '',
            content,
            flags=re.DOTALL,
        ).strip()

    @property
    def total_turns(self) -> int:
        return len(self.turns)

    @property
    def character_turns(self) -> int:
        """AI 回复总次数（用于计算摘要间隔）"""
        return sum(1 for t in self.turns if t.role == "assistant")
