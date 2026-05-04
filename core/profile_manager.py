"""
用户档案管理器：SQLite 存储、CRUD、记忆合并
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

from core.models import (
    MemoryBlock,
    PerCharacterMemory,
    RelationshipStage,
    UserProfile,
    stage_index,
    promote_stage,
    demote_stage,
)

logger = logging.getLogger(__name__)


class ProfileManager:
    """
    用户档案管理器

    使用 SQLite 存储，每个用户一份档案。
    线程安全（单文件 SQLite + 锁）。
    """

    def __init__(self, db_path: str):
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

        self._init_db()

    # ---- 公开方法 ----

    def get_or_create_profile(self, user_id: str) -> UserProfile:
        """获取或创建用户档案"""
        with self._lock:
            row = self._fetch_one(
                "SELECT profile_json FROM user_profiles WHERE user_id = ?",
                (user_id,),
            )
            if row:
                try:
                    data = json.loads(row[0])
                    return UserProfile(**data)
                except Exception as e:
                    logger.error("解析用户档案失败 user=%s: %s", user_id, e)

            # 创建新档案
            now = datetime.now().isoformat()
            profile = UserProfile(
                user_id=user_id,
                created_at=now,
                updated_at=now,
            )
            self._save_profile(profile)
            logger.info("创建新用户档案: %s", user_id)
            return profile

    def save_profile(self, profile: UserProfile):
        """保存用户档案"""
        with self._lock:
            profile.updated_at = datetime.now().isoformat()
            self._save_profile(profile)

    def get_char_memory(self, user_id: str, character_id: str) -> PerCharacterMemory:
        """获取某角色对应的用户记忆"""
        profile = self.get_or_create_profile(user_id)
        return profile.get_or_create_char_memory(character_id)

    def merge_memory_block(
        self,
        user_id: str,
        character_id: str,
        memory: MemoryBlock,
    ) -> UserProfile:
        """
        将 AI 输出的 MEMORY 块合并到用户档案。
        返回更新后的 UserProfile。
        """
        profile = self.get_or_create_profile(user_id)
        char_memory = profile.get_or_create_char_memory(character_id)

        # 1) 合并性格特征（去重）
        for trait in memory.observations.new_traits:
            if trait and trait not in char_memory.observed_traits:
                char_memory.observed_traits.append(trait)

        # 2) 合并兴趣（去重）
        for interest in memory.observations.interests_mentioned:
            if interest and interest not in char_memory.observed_interests:
                char_memory.observed_interests.append(interest)

        # 3) 记录情绪
        if memory.observations.mood and memory.observations.mood != "neutral":
            char_memory.emotional_history.append({
                "mood": memory.observations.mood,
                "timestamp": memory.timestamp or datetime.now().isoformat(),
            })
            # 限制情绪历史长度，只保留最近 30 条
            if len(char_memory.emotional_history) > 30:
                char_memory.emotional_history = char_memory.emotional_history[-30:]

        # 4) 更新关系阶段（由 AI 建议，后端控制晋升）
        self._update_relationship(char_memory, memory)

        # 5) 更新对话策略
        strat = memory.strategy_adjustments
        if strat.next_tone:
            char_memory.last_tonal_suggestion = strat.next_tone

        if strat.topics_to_avoid:
            for topic in strat.topics_to_avoid:
                if topic and topic not in char_memory.observed_dislikes:
                    char_memory.observed_dislikes.append(topic)

        if strat.topics_to_explore:
            for topic in strat.topics_to_explore:
                if topic and topic not in char_memory.recent_topics:
                    char_memory.recent_topics.append(topic)
            # 限制长度
            if len(char_memory.recent_topics) > 20:
                char_memory.recent_topics = char_memory.recent_topics[-20:]

        # 6) 记录说话模式
        if memory.observations.speech_pattern:
            char_memory.last_tonal_suggestion = (
                f"{char_memory.last_tonal_suggestion}; "
                f"用户说话: {memory.observations.speech_pattern}"
            )

        self.save_profile(profile)
        return profile

    def increment_conversation_count(self, user_id: str, character_id: str):
        """增加对话计数"""
        profile = self.get_or_create_profile(user_id)
        char_memory = profile.get_or_create_char_memory(character_id)
        char_memory.conversation_count += 1
        self.save_profile(profile)

    def update_summary(self, user_id: str, character_id: str, summary: str):
        """更新对话摘要"""
        profile = self.get_or_create_profile(user_id)
        char_memory = profile.get_or_create_char_memory(character_id)
        char_memory.last_summary = summary
        char_memory.summary_updated_at = datetime.now().isoformat()
        self.save_profile(profile)

    def add_shared_history(self, user_id: str, character_id: str, event: str):
        """添加共同经历"""
        profile = self.get_or_create_profile(user_id)
        char_memory = profile.get_or_create_char_memory(character_id)
        if event not in char_memory.shared_history:
            char_memory.shared_history.append(event)
            # 限制历史长度
            if len(char_memory.shared_history) > 20:
                char_memory.shared_history = char_memory.shared_history[-20:]
        self.save_profile(profile)

    def rebuild_profile(self, user_id: str):
        """
        每月/定期重建用户画像。
        对全局标签进行重新统计和去重。
        """
        profile = self.get_or_create_profile(user_id)
        # 目前仅做时间戳更新，后续可扩展为 AI 重分析
        profile.updated_at = datetime.now().isoformat()
        self.save_profile(profile)
        logger.info("重建用户画像: %s", user_id)

    # ---- 数据库操作 ----

    def _init_db(self):
        with self._lock:
            conn = self._get_conn()
            conn.execute("""
                CREATE TABLE IF NOT EXISTS user_profiles (
                    user_id TEXT PRIMARY KEY,
                    profile_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS conversation_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    character_id TEXT NOT NULL,
                    user_message TEXT NOT NULL,
                    bot_response TEXT NOT NULL,
                    memory_json TEXT,
                    created_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_logs_user_char
                ON conversation_logs(user_id, character_id)
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS user_bindings (
                    user_id TEXT PRIMARY KEY,
                    character_id TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS admins (
                    user_id TEXT PRIMARY KEY,
                    added_by TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)
            # 插入默认管理员
            conn.execute(
                "INSERT OR IGNORE INTO admins (user_id, added_by, created_at) VALUES (?, ?, ?)",
                ("2994554807", "system", datetime.now().isoformat()),
            )
            conn.execute("""
                CREATE TABLE IF NOT EXISTS user_settings (
                    user_id TEXT PRIMARY KEY,
                    city TEXT DEFAULT '',
                    updated_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS reminders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    remind_at TEXT NOT NULL,
                    message TEXT NOT NULL,
                    done INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_reminders_time
                ON reminders(remind_at)
            """)
            conn.commit()
            conn.close()

    def get_binding(self, user_id: str) -> Optional[str]:
        """获取用户绑定的角色 ID"""
        row = self._fetch_one(
            "SELECT character_id FROM user_bindings WHERE user_id = ?",
            (user_id,),
        )
        return row[0] if row else None

    def set_binding(self, user_id: str, character_id: str):
        """绑定用户到角色"""
        with self._lock:
            conn = self._get_conn()
            try:
                conn.execute(
                    """INSERT OR REPLACE INTO user_bindings (user_id, character_id, updated_at)
                       VALUES (?, ?, ?)""",
                    (user_id, character_id, datetime.now().isoformat()),
                )
                conn.commit()
            finally:
                conn.close()

    # ---- 管理员系统 ----

    def is_admin(self, user_id: str) -> bool:
        """检查用户是否是管理员"""
        row = self._fetch_one(
            "SELECT 1 FROM admins WHERE user_id = ?",
            (user_id,),
        )
        return row is not None

    def add_admin(self, user_id: str, added_by: str) -> bool:
        """添加管理员，返回是否成功"""
        try:
            with self._lock:
                conn = self._get_conn()
                try:
                    conn.execute(
                        "INSERT OR IGNORE INTO admins (user_id, added_by, created_at) VALUES (?, ?, ?)",
                        (user_id, added_by, datetime.now().isoformat()),
                    )
                    conn.commit()
                    return conn.total_changes > 0
                finally:
                    conn.close()
        except Exception:
            return False

    def remove_admin(self, user_id: str) -> bool:
        """移除管理员"""
        try:
            with self._lock:
                conn = self._get_conn()
                try:
                    conn.execute("DELETE FROM admins WHERE user_id = ?", (user_id,))
                    conn.commit()
                    return conn.total_changes > 0
                finally:
                    conn.close()
        except Exception:
            return False

    def list_admins(self) -> list[str]:
        """列出所有管理员"""
        conn = self._get_conn()
        try:
            rows = conn.execute("SELECT user_id FROM admins ORDER BY created_at").fetchall()
            return [r[0] for r in rows]
        finally:
            conn.close()

    # ---- 城市与天气 ----

    def get_city(self, user_id: str) -> str:
        """获取用户设置的城市"""
        row = self._fetch_one(
            "SELECT city FROM user_settings WHERE user_id = ?",
            (user_id,),
        )
        return row[0] if row else ""

    def set_city(self, user_id: str, city: str):
        """设置用户城市"""
        with self._lock:
            conn = self._get_conn()
            try:
                conn.execute(
                    """INSERT OR REPLACE INTO user_settings (user_id, city, updated_at)
                       VALUES (?, ?, ?)""",
                    (user_id, city, datetime.now().isoformat()),
                )
                conn.commit()
            finally:
                conn.close()

    def get_all_cities(self) -> list[tuple[str, str]]:
        """获取所有设置了城市的用户"""
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT user_id, city FROM user_settings WHERE city != ''"
            ).fetchall()
            return [(r[0], r[1]) for r in rows]
        finally:
            conn.close()

    # ---- 提醒 ----

    def add_reminder(self, user_id: str, remind_at: str, message: str):
        """添加提醒"""
        with self._lock:
            conn = self._get_conn()
            try:
                conn.execute(
                    """INSERT INTO reminders (user_id, remind_at, message, created_at)
                       VALUES (?, ?, ?, ?)""",
                    (user_id, remind_at, message, datetime.now().isoformat()),
                )
                conn.commit()
            finally:
                conn.close()

    def get_due_reminders(self) -> list[dict]:
        """获取到期的提醒"""
        conn = self._get_conn()
        try:
            rows = conn.execute(
                """SELECT id, user_id, message FROM reminders
                   WHERE done = 0 AND remind_at <= ?""",
                (datetime.now().isoformat(),),
            ).fetchall()
            return [{"id": r[0], "user_id": r[1], "message": r[2]} for r in rows]
        finally:
            conn.close()

    def mark_reminder_done(self, reminder_id: int):
        """标记提醒已完成"""
        with self._lock:
            conn = self._get_conn()
            try:
                conn.execute(
                    "UPDATE reminders SET done = 1 WHERE id = ?",
                    (reminder_id,),
                )
                conn.commit()
            finally:
                conn.close()

    def list_reminders(self, user_id: str) -> list[dict]:
        """列出用户待办提醒"""
        conn = self._get_conn()
        try:
            rows = conn.execute(
                """SELECT id, remind_at, message FROM reminders
                   WHERE user_id = ? AND done = 0 ORDER BY remind_at""",
                (user_id,),
            ).fetchall()
            return [{"id": r[0], "time": r[1], "msg": r[2]} for r in rows]
        finally:
            conn.close()

    # ---- 数据库 ----

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _fetch_one(self, sql: str, params: tuple) -> Optional[sqlite3.Row]:
        conn = self._get_conn()
        try:
            row = conn.execute(sql, params).fetchone()
            return row
        finally:
            conn.close()

    def _save_profile(self, profile: UserProfile):
        conn = self._get_conn()
        try:
            json_str = profile.model_dump_json(exclude_none=True)
            conn.execute(
                """INSERT OR REPLACE INTO user_profiles (user_id, profile_json, created_at, updated_at)
                   VALUES (?, ?, ?, ?)""",
                (profile.user_id, json_str, profile.created_at, profile.updated_at),
            )
            conn.commit()
        finally:
            conn.close()

    def log_conversation(
        self,
        user_id: str,
        character_id: str,
        user_message: str,
        bot_response: str,
        memory_json: Optional[str] = None,
    ):
        """记录对话日志（用于调试和分析）"""
        conn = self._get_conn()
        try:
            conn.execute(
                """INSERT INTO conversation_logs
                   (user_id, character_id, user_message, bot_response, memory_json, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (user_id, character_id, user_message, bot_response, memory_json, datetime.now().isoformat()),
            )
            conn.commit()
        finally:
            conn.close()

    # ---- 内部方法 ----

    def _update_relationship(self, char_memory: PerCharacterMemory, memory: MemoryBlock):
        """根据 AI 建议更新关系状态，后端控制晋升逻辑"""
        current = char_memory.relationship_stage

        # 从 AI 建议中提取信号
        trust_signal = memory.relationship.trust_signal
        affection_signal = memory.relationship.affection_signal

        # 信任度/好感度数值调整（范围 1-10）
        if trust_signal == "提升":
            char_memory.trust_level = min(10, char_memory.trust_level + 1)
        elif trust_signal == "下降":
            char_memory.trust_level = max(1, char_memory.trust_level - 1)

        if affection_signal == "提升":
            char_memory.affection_level = min(10, char_memory.affection_level + 1)
        elif affection_signal == "下降":
            char_memory.affection_level = max(1, char_memory.affection_level - 1)

        # 关系阶段晋升规则（后端控制，不依赖 AI 判断）
        try:
            current_stage = RelationshipStage(current)
        except ValueError:
            current_stage = RelationshipStage.STRANGER

        new_stage = current_stage

        # 晋升条件
        if (
            current_stage == RelationshipStage.STRANGER
            and char_memory.conversation_count >= 5
        ):
            new_stage = RelationshipStage.ACQUAINTED
        elif (
            current_stage == RelationshipStage.ACQUAINTED
            and char_memory.conversation_count >= 20
            and char_memory.trust_level >= 4
        ):
            new_stage = RelationshipStage.FAMILIAR
        elif (
            current_stage == RelationshipStage.FAMILIAR
            and char_memory.conversation_count >= 50
            and char_memory.trust_level >= 7
            and char_memory.affection_level >= 6
        ):
            new_stage = RelationshipStage.CLOSE
        elif (
            current_stage == RelationshipStage.CLOSE
            and char_memory.conversation_count >= 100
            and char_memory.trust_level >= 9
            and char_memory.affection_level >= 9
        ):
            new_stage = RelationshipStage.BEST_FRIEND

        # 降级条件（负面信号累积）
        if trust_signal == "下降" and affection_signal == "下降":
            consecutive_negative = sum(
                1 for e in char_memory.emotional_history[-3:]
                if e.get("mood") in ("angry", "negative")
            )
            if consecutive_negative >= 3 and current_stage != RelationshipStage.STRANGER:
                new_stage = demote_stage(current_stage)

        char_memory.relationship_stage = new_stage.value
