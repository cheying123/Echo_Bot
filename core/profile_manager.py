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

        # 1) 合并性格特征（去重+过滤+时间戳）
        import re
        for trait in memory.observations.new_traits:
            if not trait:
                continue
            if len(trait) > 15 or re.search(r'[，。！？、]', trait):
                continue
            if trait not in char_memory.observed_traits:
                char_memory.observed_traits.append(trait)
            char_memory.mark_trait_seen(trait)

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

        # 7) 更新行为模式
        self._update_behavioral_patterns(char_memory, "", "")

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
            # 迁移：给 user_settings 添加开关字段
            try:
                conn.execute("ALTER TABLE user_settings ADD COLUMN weather_on INTEGER DEFAULT 1")
            except Exception:
                pass  # 字段已存在
            try:
                conn.execute("ALTER TABLE user_settings ADD COLUMN remind_on INTEGER DEFAULT 1")
            except Exception:
                pass
            try:
                conn.execute("ALTER TABLE user_settings ADD COLUMN weather_time INTEGER DEFAULT 8")
            except Exception:
                pass
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

    # ---- 记忆压缩 ----

    def compress_all_memories(self, max_age_days: int = 30) -> int:
        """压缩所有用户的所有角色记忆，返回处理的用户数"""
        conn = self._get_conn()
        count = 0
        try:
            rows = conn.execute("SELECT user_id, profile_json FROM user_profiles").fetchall()
            for row in rows:
                try:
                    profile = UserProfile(**json.loads(row[1]))
                    changed = False
                    for cm in profile.per_character_memory.values():
                        if cm.compress(max_age_days=max_age_days):
                            changed = True
                    if changed:
                        self.save_profile(profile)
                    count += 1
                except Exception:
                    pass
        finally:
            conn.close()
        logger.info("记忆压缩完成: %d 个用户", count)
        return count

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

    def get_weather_on(self, user_id: str) -> bool:
        row = self._fetch_one(
            "SELECT weather_on FROM user_settings WHERE user_id = ?", (user_id,)
        )
        return bool(row[0]) if row else True

    def get_weather_time(self, user_id: str) -> int:
        row = self._fetch_one(
            "SELECT weather_time FROM user_settings WHERE user_id = ?", (user_id,)
        )
        return int(row[0]) if row else 8

    def set_weather_time(self, user_id: str, hour: int):
        with self._lock:
            conn = self._get_conn()
            try:
                conn.execute(
                    "INSERT OR REPLACE INTO user_settings (user_id, city, weather_on, weather_time, updated_at) VALUES (?, COALESCE((SELECT city FROM user_settings WHERE user_id = ?), ''), COALESCE((SELECT weather_on FROM user_settings WHERE user_id = ?), 1), ?, ?)",
                    (user_id, user_id, user_id, hour, datetime.now().isoformat()),
                )
                conn.commit()
            finally:
                conn.close()

    def set_weather_on(self, user_id: str, on: bool):
        with self._lock:
            conn = self._get_conn()
            try:
                conn.execute(
                    "INSERT OR REPLACE INTO user_settings (user_id, city, weather_on, updated_at) VALUES (?, COALESCE((SELECT city FROM user_settings WHERE user_id = ?), ''), ?, ?)",
                    (user_id, user_id, int(on), datetime.now().isoformat()),
                )
                conn.commit()
            finally:
                conn.close()

    def get_remind_on(self, user_id: str) -> bool:
        row = self._fetch_one(
            "SELECT remind_on FROM user_settings WHERE user_id = ?", (user_id,)
        )
        return bool(row[0]) if row else True

    def set_remind_on(self, user_id: str, on: bool):
        with self._lock:
            conn = self._get_conn()
            try:
                conn.execute(
                    "INSERT OR REPLACE INTO user_settings (user_id, city, remind_on, updated_at) VALUES (?, COALESCE((SELECT city FROM user_settings WHERE user_id = ?), ''), ?, ?)",
                    (user_id, user_id, int(on), datetime.now().isoformat()),
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

    def get_due_reminders(self, now: str = "") -> list[dict]:
        """获取到期的提醒"""
        if not now:
            try:
                from core.scheduler import _now_cst
                now = _now_cst().isoformat()
            except Exception:
                now = datetime.now().isoformat()
        conn = self._get_conn()
        try:
            rows = conn.execute(
                """SELECT id, user_id, message FROM reminders
                   WHERE done = 0 AND remind_at <= ?""",
                (now,),
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
        conv = char_memory.conversation_count
        pr = self._analyze_emotion_trend(char_memory.emotional_history)
        quality = self._calc_interaction_quality(char_memory)
        compat = getattr(char_memory, "compatibility_score", 0.5) or 0.5
        intimacy = min(5, len(char_memory.shared_history) + len(char_memory.observed_interests) // 3)

        trust = min(10, 1 + conv // 15 + intimacy + int(pr * 2) + int(compat * 2))
        affection = min(10, 1 + conv // 12 + int(quality * 3) + int(compat * 2))

        for sig, attr in [("trust_signal", "trust_level"), ("affection_signal", "affection_level")]:
            val = getattr(memory.relationship, sig, "")
            if val == "提升":
                if attr == "trust_level": trust = min(10, trust + 1)
                else: affection = min(10, affection + 1)
            elif val == "下降":
                if attr == "trust_level": trust = max(1, trust - 1)
                else: affection = max(1, affection - 1)

        char_memory.trust_level = trust
        char_memory.affection_level = affection

        progress = self._eval_progress(char_memory.relationship_stage, conv, trust, affection, pr, intimacy, compat)
        if progress["promote"]:
            from core.models import promote_stage, RelationshipStage
            char_memory.relationship_stage = promote_stage(RelationshipStage(char_memory.relationship_stage), 1).value
        elif progress["demote"]:
            from core.models import demote_stage, RelationshipStage
            char_memory.relationship_stage = demote_stage(RelationshipStage(char_memory.relationship_stage), 1).value

    @staticmethod
    def _analyze_emotion_trend(history: list) -> float:
        recent = [e for e in history[-12:] if e.get("mood")]
        return sum(1 for e in recent if e["mood"] in ("positive", "excited")) / max(len(recent), 1)

    @staticmethod
    def _calc_interaction_quality(m) -> float:
        return (min(1, len(m.observed_interests) / 10) + min(1, m.conversation_count / 50)) / 2

    @staticmethod
    def _eval_progress(stage: str, conv: int, trust: int, affection: int, pr: float, intimacy: int, compat: float = 0.5) -> dict:
        from core.models import RelationshipStage
        try:
            s = RelationshipStage(stage)
        except ValueError:
            return {"promote": False, "demote": False}
        r = {"promote": False, "demote": False}
        mult = 1.0 if compat >= 0.7 else 0.8 if compat >= 0.5 else 0.6
        rules = [(0, 5, 0, 0.0), (1, 20, 3, 0.6), (2, 50, 6, 0.6), (3, 100, 8, 0.5)]
        if s.value < len(rules):
            bc, bt, bp = rules[s.value][1], rules[s.value][2], rules[s.value][3]
            if conv >= int(bc * mult) and trust >= int(bt * mult) and pr >= bp * mult:
                r["promote"] = True
        if pr < 0.2 and s.value > 0:
            r["demote"] = True
        return r

    @staticmethod
    def _update_behavioral_patterns(memory: PerCharacterMemory, user_msg: str, bot_resp: str):
        bp = memory.behavioral_patterns or {}
        import re
        lengths = bp.get("_lengths", [])
        lengths.append(len(user_msg))
        if len(lengths) > 50: lengths = lengths[-50:]
        bp["avg_msg_len"] = sum(lengths) / len(lengths)
        bp["_lengths"] = lengths

        qs = len(re.findall(r"[？?]", user_msg))
        ts = max(1, len(re.split(r"[。！？.!?]", user_msg)))
        rates = bp.get("_qrates", [])
        rates.append(qs / ts)
        if len(rates) > 20: rates = rates[-20:]
        bp["question_rate"] = sum(rates) / len(rates)
        bp["_qrates"] = rates

        emo = len(re.findall(r"[^\w\s，。、《》？；：""''（）【】]", user_msg))
        erates = bp.get("_erates", [])
        erates.append(emo / max(len(user_msg), 1))
        if len(erates) > 20: erates = erates[-20:]
        bp["emoji_rate"] = sum(erates) / len(erates)
        bp["_erates"] = erates

        bp["reply_style"] = "简短" if bp["avg_msg_len"] < 10 else "详细" if bp["avg_msg_len"] > 30 else "中等"
        memory.behavioral_patterns = bp

    def _analyze_emotion_trend(history: list) -> float:
        recent = [e for e in history[-12:] if e.get("mood")]
        return sum(1 for e in recent if e["mood"] in ("positive", "excited")) / max(len(recent), 1)

    @staticmethod
    def _calc_interaction_quality(m) -> float:
        return (min(1, len(m.observed_interests) / 10) + min(1, m.conversation_count / 50)) / 2

    @staticmethod
    def _eval_progress(stage: str, conv: int, trust: int, affection: int, pr: float, intimacy: int) -> dict:
        from core.models import RelationshipStage
        try:
            s = RelationshipStage(stage)
        except ValueError:
            return {"promote": False, "demote": False}
        r = {"promote": False, "demote": False}
        rules = [(0, 5, 0, 0.0), (1, 20, 3, 0.6), (2, 50, 6, 0.6), (3, 100, 8, 0.5)]
        if s.value < len(rules):
            mc, mt, mp = rules[s.value][1], rules[s.value][2], rules[s.value][3]
            if conv >= mc and trust >= mt and pr >= mp:
                r["promote"] = True
        if pr < 0.2 and s.value > 0:
            r["demote"] = True
        return r

