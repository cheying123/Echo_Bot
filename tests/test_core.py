"""
Echo_Bot 核心测试

运行：python -m pytest tests/test_core.py -v
或：  python tests/test_core.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest

# 确保项目根目录在 path 中
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

# ===================================================================
# 1. 配置测试
# ===================================================================

class TestConfig(unittest.TestCase):
    """配置加载与厂商预设"""

    def test_load_default(self):
        from config import Config
        cfg = Config()
        self.assertTrue(cfg.llm.get("api_key") is not None)
        self.assertTrue(cfg.llm.get("provider", ""))

    def test_provider_presets(self):
        from config import AI_PROVIDER_PRESETS
        self.assertIn("qwen", AI_PROVIDER_PRESETS)
        self.assertIn("deepseek", AI_PROVIDER_PRESETS)
        self.assertIn("openai", AI_PROVIDER_PRESETS)
        qwen = AI_PROVIDER_PRESETS["qwen"]
        self.assertIn("dashscope", qwen["base_url"])

    def test_env_override(self):
        os.environ["AIBOT_LLM__PROVIDER"] = "test_provider"
        from config import Config
        cfg = Config()
        # 应该从环境变量读取
        self.assertEqual(cfg.llm.get("provider"), "test_provider")
        del os.environ["AIBOT_LLM__PROVIDER"]


# ===================================================================
# 2. 数据模型测试
# ===================================================================

class TestModels(unittest.TestCase):
    """Pydantic 数据模型"""

    def test_character_card(self):
        from core.models import CharacterCard
        card = CharacterCard(name="测试角色", source="测试作品")
        self.assertEqual(card.name, "测试角色")
        self.assertEqual(card.version, "1.0")
        missing = card.validate_card()
        self.assertIn("personality.core_traits", missing)

    def test_complete_character(self):
        from core.models import CharacterCard, Personality, KnowledgeBoundary, SpeechExample
        card = CharacterCard(
            name="露西亚",
            source="战双帕弥什",
            personality=Personality(
                core_traits=["坚定", "温柔"],
                speaking_style="坚定而温柔",
            ),
            speech_examples=[
                SpeechExample(user="你好", response="早上好，指挥官。"),
            ],
        )
        missing = card.validate_card()
        self.assertEqual(missing, [])  # 全部必填字段已填

    def test_memory_block(self):
        from core.models import MemoryBlock, MemoryObservation
        block = MemoryBlock(
            user_id="123",
            timestamp="2026-01-01T00:00:00",
            observations=MemoryObservation(mood="positive", new_traits=["喜欢自嘲"]),
        )
        self.assertEqual(block.observations.mood, "positive")
        self.assertEqual(block.observations.new_traits, ["喜欢自嘲"])

    def test_relationship_stage(self):
        from core.models import RelationshipStage, stage_index, promote_stage, demote_stage
        self.assertEqual(stage_index(RelationshipStage.STRANGER), 0)
        self.assertEqual(stage_index(RelationshipStage.FAMILIAR), 2)
        promoted = promote_stage(RelationshipStage.ACQUAINTED, 2)
        self.assertEqual(promoted, RelationshipStage.CLOSE)
        demoted = demote_stage(RelationshipStage.FAMILIAR, 1)
        self.assertEqual(demoted, RelationshipStage.ACQUAINTED)


# ===================================================================
# 3. 角色管理测试
# ===================================================================

class TestCharacterManager(unittest.TestCase):
    """角色卡加载与缓存"""

    @classmethod
    def setUpClass(cls):
        from config import load_config
        from core.character_manager import CharacterManager
        cls.cfg = load_config()
        cls.cm = CharacterManager(cls.cfg.paths["characters_dir"])

    def test_list_characters(self):
        chars = self.cm.list_characters()
        self.assertGreater(len(chars), 0, "至少有一个角色")
        for c in chars:
            self.assertIn("name", c)
            self.assertIn("id", c)
            self.assertIn("traits", c)

    def test_get_character(self):
        chars = self.cm.list_characters()
        card = self.cm.get_character(chars[0]["id"])
        self.assertIsNotNone(card)
        self.assertEqual(card.name, chars[0]["name"])

    def test_validate_all(self):
        chars = self.cm.list_characters()
        for c in chars:
            card = self.cm.get_character(c["id"])
            missing = card.validate_card()
            # 至少要有基础的说话风格和对话示例
            if missing:
                print(f"  警告: {c['name']} 缺少字段: {missing}")

    def test_character_lore(self):
        chars = self.cm.list_characters()
        has_lore = [c for c in chars if self.cm.get_character(c["id"]).lore]
        self.assertGreater(len(has_lore), 0, "至少有一个角色有 lore")


# ===================================================================
# 4. 提示词构建测试
# ===================================================================

class TestPromptBuilder(unittest.TestCase):
    """提示词模板渲染"""

    @classmethod
    def setUpClass(cls):
        from config import load_config
        from core.character_manager import CharacterManager
        from core.prompt_builder import PromptBuilder
        from core.models import UserProfile
        cls.cfg = load_config()
        cls.cm = CharacterManager(cls.cfg.paths["characters_dir"])
        cls.pb = PromptBuilder()
        cls.profile = UserProfile(user_id="test")

    def test_build_system_prompt(self):
        chars = self.cm.list_characters()
        card = self.cm.get_character(chars[0]["id"])
        prompt = self.pb.build_system_prompt(
            character=card,
            user_id="test",
            profile=self.profile,
        )
        self.assertIn("角色扮演协议", prompt)
        self.assertIn(card.name, prompt)
        self.assertIn("互动引擎规则", prompt)

    def test_prompt_contains_lore(self):
        chars = self.cm.list_characters()
        for c in chars:
            card = self.cm.get_character(c["id"])
            prompt = self.pb.build_system_prompt(
                character=card,
                user_id="test",
                profile=self.profile,
                user_message="你好",
            )
            if card.lore:
                self.assertIn("关键设定", prompt)
            break

    def test_prompt_with_user_message(self):
        chars = self.cm.list_characters()
        card = self.cm.get_character(chars[0]["id"])
        prompt = self.pb.build_system_prompt(
            character=card,
            user_id="test",
            profile=self.profile,
            user_message="今天心情不好",
        )
        # 提示词中应包含角色扮演协议和角色名
        self.assertIn("角色扮演协议", prompt)
        self.assertIn(card.name, prompt)


# ===================================================================
# 5. 记忆解析测试
# ===================================================================

class TestMemoryParser(unittest.TestCase):
    """MEMORY 块解析"""

    def test_extract_valid_memory(self):
        from core.memory_parser import extract_and_parse
        text = """你好呀
<<<MEMORY>>>{"user_id":"u1","observations":{"mood":"positive","new_traits":["喜欢自嘲"]},"relationship":{},"strategy_adjustments":{}}<<<END_MEMORY>>>"""
        block, clean = extract_and_parse(text)
        self.assertIsNotNone(block)
        self.assertEqual(block.observations.mood, "positive")
        self.assertEqual(clean, "你好呀")

    def test_extract_no_memory(self):
        from core.memory_parser import extract_and_parse
        block, clean = extract_and_parse("就是一句普通的话")
        self.assertIsNone(block)
        self.assertEqual(clean, "就是一句普通的话")

    def test_extract_list_speech_pattern(self):
        """AI 有时把 speech_pattern 输出为列表"""
        from core.memory_parser import extract_and_parse
        text = 'hi\n<<<MEMORY>>>{"user_id":"u1","observations":{"mood":"positive","speech_pattern":["简短直接","无修饰"]},"relationship":{},"strategy_adjustments":{}}<<<END_MEMORY>>>'
        block, clean = extract_and_parse(text)
        self.assertIsNotNone(block)
        self.assertIsInstance(block.observations.speech_pattern, str)

    def test_strip_memory_block(self):
        from core.memory_parser import strip_memory_block
        clean = strip_memory_block("你好<<<MEMORY>>><<<END_MEMORY>>>")
        self.assertEqual(clean, "你好")


# ===================================================================
# 6. 台词检索测试
# ===================================================================

class TestRetriever(unittest.TestCase):
    """台词检索器"""

    def setUp(self):
        from core.retriever import DialogueRetriever
        self.r = DialogueRetriever()

    def test_tfidf_retrieve(self):
        lines = ["你好呀", "今天天气真好", "我心情不太好"]
        results = self.r.retrieve("心情", lines, top_k=2)
        self.assertGreater(len(results), 0)
        # 应该匹配到最相关的台词（包含"心情"）
        any_match = any("心情" in r[0] for r in results)
        self.assertTrue(any_match, f"应在结果中找到包含'心情'的台词，结果: {results}")

    def test_empty_input(self):
        results = self.r.retrieve("", [])
        self.assertEqual(results, [])

    def test_chinese_tokenize(self):
        from core.retriever import TwoStageRetriever
        tokens = TwoStageRetriever()._extract_ngrams("指挥官你好")
        self.assertGreater(len(tokens), 0)
        self.assertIn("指挥", tokens)
        self.assertIn("官你", tokens)


# ===================================================================
# 7. 上下文管理测试
# ===================================================================

class TestContextManager(unittest.TestCase):
    """对话上下文窗口"""

    def setUp(self):
        from core.context_manager import ContextManager
        self.ctx = ContextManager(max_short_term_rounds=4)
        self.uid = "u1"
        self.cid = "c1"

    def test_add_and_retrieve(self):
        self.ctx.add_user_message(self.uid, self.cid, "你好")
        self.ctx.add_assistant_message(self.uid, self.cid, "你好呀")
        history = self.ctx.get_clean_history(self.uid, self.cid)
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0]["role"], "user")
        self.assertEqual(history[0]["content"], "你好")

    def test_window_limit(self):
        for i in range(10):
            self.ctx.add_user_message(self.uid, self.cid, f"msg{i}")
            self.ctx.add_assistant_message(self.uid, self.cid, f"reply{i}")
        history = self.ctx.get_clean_history(self.uid, self.cid)
        self.assertLessEqual(len(history), 4)

    def test_should_summarize(self):
        from core.models import PerCharacterMemory
        # 添加足够多的对话轮次（至少 5 轮才触发摘要）
        for i in range(6):
            self.ctx.add_user_message(self.uid, self.cid, f"msg{i}")
            self.ctx.add_assistant_message(self.uid, self.cid, f"reply{i}")

        cm = PerCharacterMemory()
        cm.conversation_count = 6
        cm.emotional_history.append({"mood": "positive"})
        cm.emotional_history.append({"mood": "negative"})
        # 情绪波动 + 达到 interval 倍数 → 触发
        result = self.ctx.should_summarize(self.uid, self.cid, char_memory=cm, interval=3)
        self.assertTrue(result)

    def test_separate_conversations(self):
        self.ctx.add_user_message(self.uid, self.cid, "你好")
        self.ctx.add_user_message(self.uid, "c2", "hello")
        self.assertEqual(self.ctx.get_context_size(self.uid, self.cid), 1)
        self.assertEqual(self.ctx.get_context_size(self.uid, "c2"), 1)


# ===================================================================
# 8. 用户档案测试
# ===================================================================

class TestProfileManager(unittest.TestCase):
    """用户档案 SQLite 存储"""

    @classmethod
    def setUpClass(cls):
        from core.profile_manager import ProfileManager
        cls.db_path = os.path.join(tempfile.gettempdir(), "test_echo_bot.db")
        cls.pm = ProfileManager(cls.db_path)

    @classmethod
    def tearDownClass(cls):
        if os.path.exists(cls.db_path):
            os.unlink(cls.db_path)

    def test_create_profile(self):
        profile = self.pm.get_or_create_profile("test_user")
        self.assertEqual(profile.user_id, "test_user")
        self.assertTrue(profile.created_at)

    def test_char_memory(self):
        cm = self.pm.get_char_memory("test_user", "char_01")
        self.assertEqual(cm.relationship_stage, "陌生人")
        self.assertEqual(cm.trust_level, 1)

    def test_save_and_load(self):
        profile = self.pm.get_or_create_profile("test_user")
        cm = profile.get_or_create_char_memory("char_01")
        cm.observed_traits.append("幽默")
        cm.trust_level = 5
        self.pm.save_profile(profile)

        loaded = self.pm.get_or_create_profile("test_user")
        loaded_cm = loaded.get_or_create_char_memory("char_01")
        self.assertIn("幽默", loaded_cm.observed_traits)
        self.assertEqual(loaded_cm.trust_level, 5)

    def test_binding(self):
        self.pm.set_binding("user_bind", "char_bind")
        result = self.pm.get_binding("user_bind")
        self.assertEqual(result, "char_bind")

    def test_admin(self):
        self.pm.add_admin("admin_test", "system")
        self.assertTrue(self.pm.is_admin("admin_test"))
        self.pm.remove_admin("admin_test")
        self.assertFalse(self.pm.is_admin("admin_test"))

    def test_city(self):
        self.pm.set_city("city_user", "北京")
        city = self.pm.get_city("city_user")
        self.assertEqual(city, "北京")

    def test_reminder(self):
        from datetime import datetime, timedelta
        future = (datetime.now() + timedelta(hours=1)).isoformat()
        self.pm.add_reminder("remind_user", future, "测试提醒")
        # 未到期的提醒不应该被返回
        due = self.pm.get_due_reminders()
        self.assertEqual(len([r for r in due if r["user_id"] == "remind_user"]), 0)

        # 到期的提醒应该被返回
        past = (datetime.now() - timedelta(hours=1)).isoformat()
        self.pm.add_reminder("remind_user2", past, "过期提醒")
        due2 = self.pm.get_due_reminders()
        self.assertTrue(any(r["message"] == "过期提醒" for r in due2))


# ===================================================================
# 9. 消息解析测试
# ===================================================================

class TestMessageParsing(unittest.TestCase):
    """消息解析与 CQ 码处理"""

    def test_clean_message(self):
        from bot.server_bot import QQBotServer
        text = QQBotServer._clean_message("[CQ:at,qq=123] 你好 [CQ:image,file=xxx.png]")
        self.assertNotIn("[CQ:at", text)
        self.assertIn("你好", text)

    def test_strip_at(self):
        from bot.server_bot import QQBotServer
        text = QQBotServer._strip_at("[CQ:at,qq=123456] hello")
        self.assertEqual(text, "hello")

    def test_split_message_no_pause(self):
        from bot.server_bot import QQBotServer
        parts = QQBotServer._split_message("你好。今天天气真好。我们出去玩吧！")
        self.assertGreaterEqual(len(parts), 1)

    def test_split_sentences(self):
        from bot.server_bot import QQBotServer
        parts = QQBotServer._split_sentences("你好。今天天气真好！我们出去玩吧？等等……")
        self.assertGreaterEqual(len(parts), 3)


# ===================================================================
# 10. 调度器测试
# ===================================================================

class TestScheduler(unittest.TestCase):
    """定时任务"""

    def test_parse_reminder_time(self):
        from core.scheduler import parse_reminder_time
        tests = [
            ("明天早上8点", True),
            ("今天下午3点", True),
            ("5分钟后", True),
            ("后天", True),
            ("2026-05-05 08:00", True),
            ("乱七八糟", False),
        ]
        for text, should_work in tests:
            result = parse_reminder_time(text)
            if should_work:
                self.assertIsNotNone(result, f"应该能解析: {text}")
            else:
                self.assertIsNone(result, f"不应该能解析: {text}")


# ===================================================================
# 11. LLM 客户端测试
# ===================================================================

class TestLLMClient(unittest.TestCase):
    """LLM API 客户端"""

    def test_retry_detection(self):
        from core.llm_client import _is_retryable, RETRYABLE_STATUS_CODES
        import httpx
        # 超时可重试
        self.assertTrue(_is_retryable(httpx.TimeoutException("timeout")))
        # 网络错误可重试
        self.assertTrue(_is_retryable(httpx.NetworkError("network")))

    def test_resolve_proxy(self):
        from core.llm_client import OpenAIClient
        proxy = OpenAIClient._resolve_proxy({"proxy": {}})
        self.assertIsNone(proxy)

    def test_llm_message(self):
        from core.llm_client import LLMMessage
        msg = LLMMessage("user", "你好")
        openai_dict = msg.to_openai()
        self.assertEqual(openai_dict["role"], "user")
        self.assertEqual(openai_dict["content"], "你好")


# ===================================================================
# 12. 踢脚回复测试
# ===================================================================

class TestFallback(unittest.TestCase):
    """AI 失败兜底"""

    def test_fallback_exists(self):
        from core.engine import _FALLBACK_REPLIES
        self.assertGreater(len(_FALLBACK_REPLIES), 0)
        for name, replies in _FALLBACK_REPLIES.items():
            self.assertGreater(len(replies), 0, f"{name} 没有兜底回复")

    def test_fallback_reply(self):
        from core.engine import DialogueEngine
        from config import load_config
        from core.character_manager import CharacterManager
        from core.profile_manager import ProfileManager
        from core.models import UserProfile
        cfg = load_config()
        cm = CharacterManager(cfg.paths["characters_dir"])
        pm = ProfileManager(os.path.join(tempfile.gettempdir(), "test_fallback.db"))
        engine = DialogueEngine(cm, pm)
        profile = UserProfile(user_id="test")
        chars = cm.list_characters()
        card = cm.get_character(chars[0]["id"])
        cmem = profile.get_or_create_char_memory(card.name)
        reply, memory = engine._fallback_reply(card, "test", chars[0]["id"], profile, cmem)
        self.assertIsNotNone(reply)
        self.assertGreater(len(reply), 0)
        os.unlink(os.path.join(tempfile.gettempdir(), "test_fallback.db"))


# ===================================================================
# 13. 插件系统测试
# ===================================================================

class TestPluginManager(unittest.TestCase):
    """插件系统"""

    def test_plugin_base(self):
        from core.plugin_manager import Plugin
        p = Plugin()
        self.assertEqual(p.name, "unnamed")

    def test_create_plugin(self):
        from core.plugin_manager import Plugin
        class TestPlugin(Plugin):
            name = "test"
            description = "测试插件"
        p = TestPlugin()
        self.assertEqual(p.name, "test")


# ===================================================================
# 14. 消息拆分测试
# ===================================================================

class TestMessageSplitting(unittest.TestCase):
    """消息拆分逻辑"""

    def test_bullet_detection(self):
        from bot.server_bot import QQBotServer
        text1 = "🎭 角色\n  /帮助"
        text2 = "指挥官你好"
        # 带格式的文字不拆分
        parts1 = QQBotServer._split_message(text1)
        self.assertEqual(parts1, [text1])
        # 普通文本按句子拆分

    def test_pause_marker(self):
        from bot.server_bot import QQBotServer
        parts = QQBotServer._split_message("hello[pause]world")
        self.assertEqual(len(parts), 2)
        self.assertEqual(parts[0], "hello")
        self.assertEqual(parts[1], "world")

    def test_short_text_no_split(self):
        from bot.server_bot import QQBotServer
        parts = QQBotServer._split_message("你好")
        self.assertEqual(parts, ["你好"])


# ===================================================================
# 运行
# ===================================================================

if __name__ == "__main__":
    # 以详细模式运行所有测试
    unittest.main(verbosity=2)
