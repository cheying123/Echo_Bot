"""
QQ Bot 服务器 — 对接 go-cqhttp / Lagrange

通信方式：Reverse WebSocket
  go-cqhttp 配置 ws_reverse 主动连接到此服务器。

流程：
  go-cqhttp  --[WS 推送事件]--> server_bot
  server_bot --[HTTP API]------> go-cqhttp 发送回复

go-cqhttp config.yml 示例：
  ws_reverse_servers:
    - enable: true
      reverse_url: ws://你的服务器IP:8765/ws
      reverse_reconnect_interval: 3000
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from typing import Optional

import httpx
import websockets
from websockets.server import WebSocketServer

from core.engine import DialogueEngine
from core.plugin_manager import PluginManager
from core.scheduler import Scheduler, parse_reminder_time

logger = logging.getLogger(__name__)


class QQBotServer:
    """
    QQ Bot 服务器

    用法：
        server = QQBotServer(engine, cfg.server)
        await server.start()
    """

    def __init__(
        self,
        engine: DialogueEngine,
        host: str = "0.0.0.0",
        ws_port: int = 8765,
        http_api_url: str = "http://127.0.0.1:5700",
        http_api_token: str = "",
    ):
        self.engine = engine
        self.host = host
        self.ws_port = ws_port

        # 插件系统
        self.plugin_mgr = PluginManager("plugins")
        self.plugin_mgr.load_all()

        # 消息 ID 自增（用于 echo）
        self._msg_id = 0

        # 当前 WebSocket 连接
        self._ws: Optional[websockets.WebSocketServerProtocol] = None
        # 主动对话用的 event 缓存（最近一条消息的事件结构）
        self._last_events: dict[str, dict] = {}

        # 主动对话配置
        self._proactive_interval = 60 * 60 * 2  # 默认 2 小时无消息则主动说话
        self._proactive_check = 60 * 10  # 每 10 分钟检查一次
        # 群聊活跃度追踪
        self._group_activity: dict[str, list[dict]] = {}  # group_key -> [messages]
        self._group_last_reply: dict[str, float] = {}  # group_key -> last reply time
        # 群聊风格学习
        self._group_styles: dict[str, dict] = {}  # group_key -> {freq: {}, emoticons: [], endings: []}
        # 个人风格学习（按用户）
        self._user_styles: dict[str, dict] = {}  # user_id -> {freq: {}, emoticons: [], endings: []}
        # 群聊对话连续性追踪（最近 @过的会话，2分钟内免 @继续对话）
        self._group_engaged: dict[str, float] = {}  # group_key -> last @ time
        # 定时任务
        self._scheduler: Optional[Scheduler] = None

    # ---- 生命周期 ----

    async def start(self):
        """启动 WebSocket 服务器（永久运行）"""
        logger.info(
            "启动 QQ Bot 服务器: ws://%s:%s",
            self.host, self.ws_port,
        )
        async with websockets.serve(
            self._handle_connection,
            self.host,
            self.ws_port,
            ping_interval=30,
            ping_timeout=10,
            max_size=2 ** 20,  # 1MB 消息上限
        ):
            # 插件启动钩子
            asyncio.ensure_future(self.plugin_mgr.dispatch_startup())
            # 启动后台任务
            asyncio.ensure_future(self._proactive_loop())
            # 启动定时任务（天气预报 + 日程提醒）
            self._scheduler = Scheduler(
                self.engine.profile_mgr,
                self._send_notification,
            )
            asyncio.ensure_future(self._scheduler.start())
            await asyncio.Future()

    async def stop(self):
        """停止服务器"""
        if self._ws:
            await self._ws.close()

    # ---- WebSocket 事件处理 ----

    async def _handle_connection(self, ws: websockets.WebSocketServerProtocol):
        """处理 go-cqhttp 的连接"""
        peer = ws.remote_address
        logger.info("go-cqhttp 已连接: %s", peer)
        self._ws = ws

        try:
            async for raw_message in ws:
                try:
                    event = json.loads(raw_message)
                except json.JSONDecodeError:
                    logger.warning("收到非 JSON 消息: %s", str(raw_message)[:100])
                    continue

                await self._dispatch_event(event)

        except websockets.exceptions.ConnectionClosed as e:
            logger.info("go-cqhttp 断开: %s  code=%s", peer, e.code)
        except Exception as e:
            logger.error("WebSocket 异常: %s", e)
        finally:
            self._ws = None

    async def _dispatch_event(self, event: dict):
        """分发事件"""
        post_type = event.get("post_type", "")

        if post_type == "message":
            await self._handle_message(event)
        elif post_type == "meta_event":
            pass  # 心跳，忽略
        elif post_type == "notice":
            pass  # 通知，暂不处理
        elif post_type == "request":
            pass  # 请求，暂不处理

    # ---- 消息处理 ----

    async def _handle_message(self, event: dict):
        """处理单条消息"""
        msg_type = event.get("message_type", "")  # private | group
        user_id = str(event.get("user_id", ""))
        bind_key = self._get_bind_key(event)  # private_xxx or group_xxx
        raw_message, sticker_text = self._extract_message(event)
        if sticker_text and not raw_message.strip():
            raw_message = sticker_text
        raw_message = self._clean_message(raw_message)

        if not raw_message or not bind_key:
            return

        # ---- 系统命令（群聊中斜杠命令不需要 @） ----
        if raw_message.startswith("/"):
            if msg_type == "group":
                raw_message = self._strip_at(raw_message)
            await self._handle_command(raw_message, bind_key, event)
            return

        # ---- 群聊处理 ----
        if msg_type == "group":
            import time as _time
            self._track_group_message(bind_key, raw_message, user_id)

            if self._is_at_bot(event):
                raw_message = self._strip_at(raw_message)
                self._group_engaged[bind_key] = _time.time()  # 标记对话中
            else:
                # 最近 @ 过（2分钟内）→ 继续对话，免 @
                engaged = self._group_engaged.get(bind_key, 0)
                if _time.time() - engaged < 120:
                    pass  # 保持 raw_message 不变，继续回复
                elif not await self._should_chime_in(bind_key, event):
                    return

        # 保存事件用于主动对话
        await self._store_event(bind_key, event)

        character_id = self._get_user_character(bind_key)
        if not character_id:
            # 默认绑定到露西亚
            chars = self.engine.char_mgr.list_characters()
            default = None
            for c in chars:
                if c["name"] == "露西亚":
                    default = c
                    break
            if not default and chars:
                default = chars[0]
            if default:
                character_id = default["id"]
                self._set_user_character(bind_key, character_id)
                await self._send_switch_greeting(event, character_id)
                return
            # 没有角色时提示
            await self._reply(event, "暂无可用角色。")
            return

        # 群聊时注入风格上下文
        if msg_type == "group":
            group_style = self._get_group_style(bind_key)
            if group_style:
                raw_message = f"[群聊风格: {group_style}] {raw_message}"

        # 调用引擎
        try:
            # 群聊用 group_群号 作为记忆隔离 key，私聊用 QQ 号
            memory_user = bind_key if msg_type == "group" else user_id
            reply, memory_data = await self.engine.process_message(
                user_message=raw_message,
                user_id=memory_user,
                character_id=character_id,
            )

            # 群聊时也按 QQ 号保存一份用户画像
            if msg_type == "group" and memory_data:
                user_profile = self.engine.profile_mgr.get_or_create_profile(f"user_{user_id}")
                user_cm = user_profile.get_or_create_char_memory(character_id)
                # 合并关键数据
                traits = memory_data.get("observations", {}).get("new_traits", [])
                for t in traits:
                    if t and t not in user_cm.observed_traits:
                        user_cm.observed_traits.append(t)
                mood = memory_data.get("observations", {}).get("mood", "")
                if mood and mood != "neutral":
                    user_cm.emotional_history.append({"mood": mood, "timestamp": datetime.now().isoformat()})
                user_cm.conversation_count += 1
                interests = memory_data.get("observations", {}).get("interests_mentioned", [])
                for i in interests:
                    if i and i not in user_cm.observed_interests:
                        user_cm.observed_interests.append(i)
                self.engine.profile_mgr.save_profile(user_profile)

            if reply:
                import time as _time2
                if msg_type == "group":
                    self._group_engaged[bind_key] = _time2.time()
                reply = await self._attach_sticker(reply, character_id)
                reply = await self.plugin_mgr.dispatch_message(event, reply)
                if reply:
                    await self._reply(event, reply)
        except Exception as e:
            logger.error("处理消息异常 user=%s: %s", user_id, e)
            await self._reply(event, "（暂时无法回应……）")

    # ---- 群聊时机判断 ----

    def _track_group_message(self, bind_key: str, message: str, user_id: str):
        """记录群聊消息到活跃度追踪，同时学习说话风格"""
        import time
        if bind_key not in self._group_activity:
            self._group_activity[bind_key] = []
        self._group_activity[bind_key].append({
            "text": message[:100],
            "user": user_id,
            "time": time.time(),
        })
        self._group_activity[bind_key] = self._group_activity[bind_key][-10:]

        # 风格学习（群聊 + 个人）
        self._learn_group_style(bind_key, message)
        self._learn_user_style(user_id, message)
        # 不回复也轻量保存用户画像
        self._save_user_traits(user_id, message)

    def _learn_group_style(self, bind_key: str, message: str):
        """从消息中学习群聊的说话风格"""
        import re
        if bind_key not in self._group_styles:
            self._group_styles[bind_key] = {"freq": {}, "emoticons": [], "endings": {}}

        style = self._group_styles[bind_key]

        # 提取中文/英文单词
        words = re.findall(r'[一-鿿\w]+', message.lower())
        for w in words:
            if len(w) >= 2:
                style["freq"][w] = style["freq"].get(w, 0) + 1

        # 提取表情符号
        emoticons = re.findall(r'[\U0001F600-\U0001F9FF☀-➿]', message)
        for e in emoticons:
            if e not in style["emoticons"]:
                style["emoticons"].append(e)

        # 提取句尾特征
        endings = re.findall(r'[。！？～~嘛啦哦呢哎哟哇]|[哈]+$', message.strip())
        for e in endings:
            style["endings"][e] = style["endings"].get(e, 0) + 1

    def _save_user_traits(self, user_id: str, message: str):
        """每消息轻量分析：情绪+性格+兴趣，不回复也记录"""
        import re
        try:
            profile = self.engine.profile_mgr.get_or_create_profile(f"user_{user_id}")
            all_chars = self.engine.char_mgr.list_characters()

            # ---- 情绪检测 ----
            mood = self._detect_mood(message)

            for c in all_chars:
                cm = profile.get_or_create_char_memory(c["id"])
                cm.conversation_count += 1

                # 记录情绪
                if mood and mood != "neutral":
                    cm.emotional_history.append({"mood": mood, "timestamp": datetime.now().isoformat()})
                    if len(cm.emotional_history) > 30:
                        cm.emotional_history = cm.emotional_history[-30:]

                # ---- 性格特征检测 ----
                trait = self._detect_trait(message)
                if trait and trait not in cm.observed_traits:
                    cm.observed_traits.append(trait)

                # ---- 兴趣关键词提取 ----
                interest_keywords = ["喜欢", "想学", "想玩", "最近在看", "推荐", "好玩", "好看"]
                for kw in interest_keywords:
                    if kw in message:
                        # 取关键词后面的内容
                        idx = message.find(kw) + len(kw)
                        topic = message[idx:idx+15].strip().rstrip("，。！？的了")
                        if topic and len(topic) >= 2:
                            # 检查是否已经是兴趣的一部分
                            existing = [i for i in cm.observed_interests if topic[:6] in i or any(word in i for word in topic.split())]
                            if not existing:
                                cm.observed_interests.append(topic)
                                break
                break  # 只处理第一个角色
            self.engine.profile_mgr.save_profile(profile)
        except Exception:
            pass

    @staticmethod
    def _detect_mood(message: str) -> str:
        """从文本中检测情绪（轻量关键词版）"""
        if any(w in message for w in ["😂", "🤣", "笑死", "太棒", "开心", "高兴", "哈哈", "嘻嘻", "好爽", "绝了", "爱了"]):
            return "positive"
        if any(w in message for w in ["😭", "😢", "难过", "伤心", "想哭", "失落", "低落"]):
            return "sad"
        if any(w in message for w in ["😡", "🤬", "气死", "烦死", "无语", "火大", "忍不"]):
            return "angry"
        if any(w in message for w in ["累", "压力", "烦躁", "焦虑", "好烦", "难受", "唉"]):
            return "negative"
        return "neutral"

    @staticmethod
    def _detect_trait(message: str) -> str:
        """从文本中检测性格特征"""
        import re
        if re.search(r'我[就]?是[个]?(废物|菜|不行|垃圾)', message):
            return "喜欢自嘲"
        if re.search(r'哈哈|笑死|hhh|hah|😂|🤣', message) and len(message) < 30:
            return "开朗"
        if message.startswith("我觉得") or message.startswith("我认为"):
            return "有主见"
        if "?" in message or "？" in message:
            if len(message) < 20:
                return "爱提问"
        return ""

    def _learn_user_style(self, user_id: str, message: str):
        """从用户消息中学习个人说话风格"""
        import re
        if user_id not in self._user_styles:
            self._user_styles[user_id] = {"freq": {}, "emoticons": [], "endings": {}}
        style = self._user_styles[user_id]

        words = re.findall(r'[一-鿿\w]+', message.lower())
        for w in words:
            if len(w) >= 2:
                style["freq"][w] = style["freq"].get(w, 0) + 1
        emoticons = re.findall(r'[\U0001F600-\U0001F9FF☀-➿]', message)
        for e in emoticons:
            if e not in style["emoticons"]:
                style["emoticons"].append(e)
        endings = re.findall(r'[。！？～~嘛啦哦呢哎哟哇]|[哈]+$', message.strip())
        for e in endings:
            style["endings"][e] = style["endings"].get(e, 0) + 1

    def _get_user_style_summary(self, user_id: str) -> str:
        """生成用户个人风格描述"""
        style = self._user_styles.get(user_id)
        if not style or not style["freq"]:
            return ""
        common = {"的", "了", "是", "不", "我", "有", "就", "在", "也", "都", "说", "和", "这", "你", "他", "一个"}
        top = sorted([(w, c) for w, c in style["freq"].items() if w not in common], key=lambda x: -x[1])[:8]
        if not top:
            return ""
        words = "、".join(w for w, _ in top)
        emo = "".join(style["emoticons"][:5]) if style["emoticons"] else ""
        return f"常用词: {words}" + (f" {emo}" if emo else "")

    def _get_group_style(self, bind_key: str) -> str:
        """生成群聊风格描述字符串"""
        style = self._group_styles.get(bind_key)
        if not style or not style["freq"]:
            return ""

        parts = []

        # 高频词（排除常见词）
        common_words = {"的", "了", "是", "不", "我", "有", "就", "在", "也", "都", "说", "和", "这", "你", "他", "一个"}
        top_words = sorted(
            [(w, c) for w, c in style["freq"].items() if w not in common_words],
            key=lambda x: -x[1],
        )[:6]
        if top_words:
            words_str = "、".join(w for w, _ in top_words)
            parts.append(f"常用词: {words_str}")

        # 常用表情
        if style["emoticons"]:
            emo_str = "".join(style["emoticons"][:5])
            parts.append(f"常见表情: {emo_str}")

        # 句尾特征
        if style["endings"]:
            top_endings = sorted(style["endings"].items(), key=lambda x: -x[1])[:4]
            endings_str = "".join(e for e, _ in top_endings)
            parts.append(f"句尾习惯: {endings_str}")

        return "，".join(parts) if parts else ""

    async def _should_chime_in(self, bind_key: str, event: dict) -> bool:
        """判断是否要在群里主动插话"""
        import time, random
        # 没绑定角色不插话
        char_id = self._get_user_character(bind_key)
        if not char_id:
            return False

        # 冷却检查（至少 30 秒后才能再次主动说话）
        now = time.time()
        last_reply = self._group_last_reply.get(bind_key, 0)
        if now - last_reply < 30:
            return False

        # 活跃度检查：最近 3 条消息是否在 5 分钟内
        activity = self._group_activity.get(bind_key, [])
        recent = [m for m in activity if now - m["time"] < 300]
        if len(recent) < 2:
            return False

        # 随机概率（25% 概率插话）
        if random.random() > 0.25:
            return False

        # 更新冷却时间
        self._group_last_reply[bind_key] = now
        return True

    def _get_group_context(self, bind_key: str) -> str:
        """获取最近群聊上下文"""
        import time
        activity = self._group_activity.get(bind_key, [])
        recent = [m for m in activity if time.time() - m["time"] < 300]
        if not recent:
            return ""
        # 取最近 3 条消息作为上下文
        context_lines = [m["text"][:60] for m in recent[-3:]]
        return " | ".join(context_lines)

    # ---- 命令处理 ----

    async def _handle_command(self, cmd: str, bind_key: str, event: dict):
        """处理斜杠命令"""
        cmd = cmd[1:].strip().lower()
        parts = cmd.split(maxsplit=1)
        action = parts[0] if parts else ""
        arg = parts[1] if len(parts) > 1 else ""

        # 插件命令优先处理
        handled = await self.plugin_mgr.dispatch_command(action, arg, event, bind_key)
        if handled:
            return

        # 中文命令优先，英文别名向后兼容
        if action in ("切换", "switch", "char", "选择"):
            await self._cmd_switch(bind_key, arg, event)
        elif action in ("角色", "roles"):
            await self._cmd_list_roles(event)
        elif action in ("档案", "profile"):
            await self._cmd_profile(bind_key, arg, event)
        elif action in ("状态", "status", "mood"):
            await self._cmd_status(bind_key, event)
        elif action in ("设置城市", "setcity", "城市"):
            await self._cmd_setcity(bind_key, arg, event)
        elif action in ("天气", "weather"):
            await self._cmd_weather(bind_key, arg, event)
        elif action in ("提醒", "remind", "reminder"):
            await self._cmd_remind(bind_key, arg, event)
        elif action in ("待办", "listremind", "我的提醒"):
            await self._cmd_list_remind(bind_key, event)
        elif action in ("统计", "stats"):
            await self._cmd_stats(bind_key, event)
        elif action in ("添加角色", "addchar"):
            await self._cmd_addchar(bind_key, event)
        elif action in ("删除角色", "removechar", "del角色"):
            await self._cmd_removechar(bind_key, arg, event)
        elif action in ("重载", "reload"):
            await self._cmd_reload(bind_key, event)
        elif action in ("管理员", "admin"):
            await self._cmd_admin(bind_key, arg, event)
        elif action in ("帮助", "help"):
            await self._cmd_help(event)
        else:
            await self._reply(event, f"未知命令，发送 /帮助 查看可用命令。")

    async def _cmd_switch(self, bind_key: str, arg: str, event: dict):
        if not arg:
            await self._reply(event, "用法: /switch <角色名>")
            return
        chars = self.engine.char_mgr.list_characters()
        matched = None
        for c in chars:
            if arg == c["id"] or arg == c["name"]:
                matched = c
                break
        if not matched:
            names = "、".join(c["name"] for c in chars)
            await self._reply(event, f"未找到角色「{arg}」。可用角色: {names}")
            return
        self._set_user_character(bind_key, matched["id"])
        await self._send_switch_greeting(event, matched["id"])

    async def _cmd_list_roles(self, event: dict):
        chars = self.engine.char_mgr.list_characters()
        if not chars:
            await self._reply(event, "暂无可用角色。")
            return
        lines = ["可用角色："]
        for c in chars:
            traits = "、".join(c["traits"][:2])
            lines.append(f"  · {c['name']} — {traits}")
        await self._reply(event, "\n".join(lines))

    async def _cmd_profile(self, bind_key: str, arg: str, event: dict):
        """查看用户统一画像（跨所有角色合并）"""
        target_key = bind_key
        target_user_id = bind_key.replace("private_", "").replace("group_", "")

        if arg:
            qq = arg.strip()
            if qq.isdigit():
                target_user_id = qq
                target_key = f"private_{qq}"
            else:
                await self._reply(event, "用法: /档案 或 /档案 <QQ号> 查看别人的画像")
                return

        # 获取用户的所有画像数据（私聊 + 群聊 + 跨角色）
        profile = self.engine.profile_mgr.get_or_create_profile(target_key)
        user_profile = self.engine.profile_mgr.get_or_create_profile(f"user_{target_user_id}")
        is_self = target_user_id == bind_key.replace("private_", "").replace("group_", "")

        # 遍历所有角色的记忆，合并为一个统一画像
        traits = set()
        interests = set()
        dislikes = set()
        total_convs = 0
        summary = ""

        all_memories = {}
        all_memories.update(profile.per_character_memory)
        all_memories.update(user_profile.per_character_memory)

        for char_id, cm in all_memories.items():
            traits.update(cm.observed_traits)
            interests.update(cm.observed_interests)
            dislikes.update(cm.observed_dislikes)
            total_convs += cm.conversation_count
        if not summary and all_memories.values():
            sm = [m.last_summary for m in all_memories.values() if m.last_summary]
            if sm:
                summary = max(sm, key=len)

        label = "我的" if is_self else f"用户 {target_user_id} 的"

        if total_convs == 0 and not traits and not interests:
            await self._reply(event, f"暂无「{label}」画像数据，聊过天后才会生成。")
            return

        lines = [f"📋 {label}画像"]
        lines.append(f"├─ 对话 {total_convs} 轮")

        if traits:
            lines.append(f"├─ 性格：{'、'.join(list(traits)[:8])}")
        if interests:
            lines.append(f"├─ 兴趣：{'、'.join(list(interests)[:6])}")
        if dislikes:
            lines.append(f"├─ 反感：{'、'.join(list(dislikes)[:4])}")
        if summary:
            lines.append(f"├─ 近况：{summary[:80]}")

        user_style = self._get_user_style_summary(target_user_id)
        if user_style:
            lines.append(f"└─ 风格：{user_style}")

        await self._reply(event, "\n".join(lines))

    async def _cmd_status(self, bind_key: str, event: dict):
        """显示当前角色的情绪、关系和语气"""
        profile = self.engine.profile_mgr.get_or_create_profile(bind_key)
        char_id = self._get_user_character(bind_key)
        if not char_id:
            await self._reply(event, "请先绑定角色。")
            return

        card = self.engine.char_mgr.get_character(char_id)
        name = card.name if card else char_id
        cm = profile.get_or_create_char_memory(char_id)

        # 最近情绪
        recent_mood = "未知"
        if cm.emotional_history:
            recent = cm.emotional_history[-1]
            recent_mood = recent.get("mood", "neutral")

        # 语气建议
        tone = cm.last_tonal_suggestion or "默认"

        lines = [
            f"【{name}】",
            f"情绪: {recent_mood}",
            f"关系: {cm.relationship_stage}",
            f"语气: {tone}",
        ]
        await self._reply(event, "\n".join(lines))

    async def _cmd_help(self, event: dict):
        await self._reply(event, (
            "🎭 角色\n"
            "  /切换 <角色名>     切换角色\n"
            "  /角色             查看可用角色\n"
            "  /状态             情绪/关系/语气\n"
            "  /档案             你的详细画像\n"
            "\n☀️ 生活\n"
            "  /设置城市 <城市>   设置城市\n"
            "  /天气             天气预报开关/时间\n"
            "  /提醒 <时间> <事>  设置提醒\n"
            "  /待办             查看待办提醒\n"
            "\n🔧 管理员\n"
            "  /管理员 list/add/remove\n"
            "  /重载             重载角色卡\n"
            "  /添加角色         添加角色指引\n"
            "  /删除角色 <名>    删除角色\n"
            "  /统计             运行统计\n"
            "\n💡 直接发消息和当前角色聊天\n"
            "首次使用：/角色 → /切换 露西亚 → 聊天"
        ))

    # ---- 城市与提醒 ----

    async def _cmd_weather(self, bind_key: str, arg: str, event: dict):
        user_id = bind_key.replace("private_", "").replace("group_", "")
        parts = arg.strip().lower().split(maxsplit=1)
        sub = parts[0] if parts else ""
        val = parts[1] if len(parts) > 1 else ""

        if sub in ("on", "开", "开启"):
            self.engine.profile_mgr.set_weather_on(user_id, True)
            t = self.engine.profile_mgr.get_weather_time(user_id)
            await self._reply(event, f"天气预报已开启，每天早上 {t} 点推送。")
        elif sub in ("off", "关", "关闭"):
            self.engine.profile_mgr.set_weather_on(user_id, False)
            await self._reply(event, "天气预报已关闭。")
        elif sub in ("time", "时间"):
            h = val.strip()
            if h.isdigit() and 0 <= int(h) <= 23:
                self.engine.profile_mgr.set_weather_time(user_id, int(h))
                await self._reply(event, f"天气预报已设为每天 {h} 点推送。")
            else:
                await self._reply(event, "请输入 0-23 之间的小时数，如 /weather time 8")
        else:
            status = "开启" if self.engine.profile_mgr.get_weather_on(user_id) else "关闭"
            t = self.engine.profile_mgr.get_weather_time(user_id)
            await self._reply(event, f"天气预报: {status} | 推送时间: 每天 {t} 点\n/weather on/off 开关\n/weather time <小时> 设置时间")

    async def _cmd_setcity(self, bind_key: str, arg: str, event: dict):
        if not arg:
            await self._reply(event, "用法: /setcity <城市名>，例如 /setcity 北京")
            return
        user_id = bind_key.replace("private_", "").replace("group_", "")
        self.engine.profile_mgr.set_city(user_id, arg.strip())
        await self._reply(event, f"已设置城市为「{arg.strip()}」，每天早上 7 点推送天气预报。")

    async def _cmd_remind(self, bind_key: str, arg: str, event: dict):
        user_id = bind_key.replace("private_", "").replace("group_", "")
        cmd = arg.strip().lower()

        # 开关
        if cmd in ("on", "开", "开启"):
            self.engine.profile_mgr.set_remind_on(user_id, True)
            await self._reply(event, "日程提醒已开启。")
            return
        elif cmd in ("off", "关", "关闭"):
            self.engine.profile_mgr.set_remind_on(user_id, False)
            await self._reply(event, "日程提醒已关闭。")
            return

        if not cmd:
            status = "开启" if self.engine.profile_mgr.get_remind_on(user_id) else "关闭"
            await self._reply(event, f"日程提醒当前状态: {status}\n/remind on 开启\n/remind off 关闭\n/remind <时间> <事项> 设置提醒")
            return

        # 设置提醒
        parts = arg.split(maxsplit=1)
        if len(parts) >= 2:
            time_text = parts[0]
            content = parts[1]
            parsed = parse_reminder_time(time_text)
            if parsed:
                self.engine.profile_mgr.add_reminder(user_id, parsed, content)
                await self._reply(event, f"已设置提醒：{time_text} {content}")
                return
        parsed = parse_reminder_time(arg)
        if parsed:
            await self._reply(event, f"已设置提醒：{arg}")
            self.engine.profile_mgr.add_reminder(user_id, parsed, arg)
        else:
            await self._reply(event, "无法识别时间，试试「明天早上8点 开会」这样的格式")

    async def _cmd_list_remind(self, bind_key: str, event: dict):
        user_id = bind_key.replace("private_", "").replace("group_", "")
        reminders = self.engine.profile_mgr.list_reminders(user_id)
        if not reminders:
            await self._reply(event, "暂无待办提醒。")
            return
        lines = ["待办提醒:"]
        for r in reminders:
            lines.append(f"  [{r['time'][:16]}] {r['msg']}")
        await self._reply(event, "\n".join(lines))

    async def _send_notification(self, user_id: str, text: str):
        """发送通知消息到用户（被调度器调用）"""
        if not self._ws:
            logger.warning("通知发送失败：WebSocket 未连接")
            return
        try:
            action = {
                "action": "send_msg",
                "params": {
                    "message_type": "private",
                    "user_id": int(user_id),
                    "message": text,
                },
            }
            await self._ws.send(json.dumps(action))
            logger.info("通知已发送 user=%s", user_id)
        except Exception as e:
            logger.error("发送通知失败: %s", e)

    # ---- 统计与重载 ----

    async def _cmd_stats(self, bind_key: str, event: dict):
        """显示运行统计"""
        user_id_num = bind_key.replace("private_", "").replace("group_", "")
        eng = self.engine
        char_id = self._get_user_character(bind_key)
        char_name = "未绑定"
        conv_count = 0
        if char_id:
            card = eng.char_mgr.get_character(char_id)
            char_name = card.name if card else char_id
            profile = eng.profile_mgr.get_or_create_profile(
                bind_key if event.get("message_type") == "group" else user_id_num
            )
            cm = profile.get_or_create_char_memory(char_id)
            conv_count = cm.conversation_count

        lines = [
            f"角色: {char_name}",
            f"对话: {conv_count} 轮",
            f"API: {eng.total_calls} 次 (失败 {eng.total_errors})",
        ]
        if eng.total_time > 0:
            avg = eng.total_time / max(eng.total_calls, 1)
            lines.append(f"平均响应: {avg:.1f}s")
        await self._reply(event, "\n".join(lines))

    async def _cmd_reload(self, bind_key: str, event: dict):
        """重新加载角色卡（管理员）"""
        user_id_num = bind_key.replace("private_", "").replace("group_", "")
        if not self.engine.profile_mgr.is_admin(user_id_num):
            await self._reply(event, "你没有权限执行此操作。")
            return
        try:
            self.engine.char_mgr.reload()
            chars = self.engine.char_mgr.list_characters()
            await self._reply(event, f"角色卡已重新加载，共 {len(chars)} 个角色。")
        except Exception as e:
            logger.error("重载角色卡失败: %s", e)
            await self._reply(event, f"重载失败: {e}")

    # ---- 管理员命令 ----

    async def _cmd_admin(self, bind_key: str, arg: str, event: dict):
        user_id = bind_key.replace("private_", "").replace("group_", "")
        if not self.engine.profile_mgr.is_admin(user_id):
            await self._reply(event, "你没有权限执行此操作。")
            return

        sub_parts = arg.split(maxsplit=1) if arg else []
        sub_action = sub_parts[0] if sub_parts else ""
        sub_arg = sub_parts[1] if len(sub_parts) > 1 else ""

        if sub_action == "list":
            admins = self.engine.profile_mgr.list_admins()
            lines = ["管理员列表:"] + [f"  - {a}" for a in admins]
            await self._reply(event, "\n".join(lines))

        elif sub_action == "add" and sub_arg:
            target = sub_arg.strip()
            if self.engine.profile_mgr.add_admin(target, user_id):
                await self._reply(event, f"已将 {target} 添加为管理员。")
            else:
                await self._reply(event, "添加失败，可能已是管理员。")

        elif sub_action == "remove" and sub_arg:
            target = sub_arg.strip()
            if self.engine.profile_mgr.remove_admin(target):
                await self._reply(event, f"已移除管理员 {target}。")
            else:
                await self._reply(event, "移除失败或该用户不是管理员。")

        else:
            await self._reply(event, (
                "管理员命令:\n"
                "  /管理员 list            查看列表\n"
                "  /管理员 add <QQ号>      添加\n"
                "  /管理员 remove <QQ号>   移除"
            ))

    # ---- 表情包 ----

    async def _attach_sticker(self, text: str, character_id: str) -> str:
        """将 [sticker] 替换为角色表情包图片"""
        if "[sticker]" not in text:
            return text

        card = self.engine.char_mgr.get_character(character_id)
        if not card or not card.sticker_pack:
            return text.replace("[sticker]", "").strip()

        import random
        url = random.choice(card.sticker_pack)
        cq_code = f"[CQ:image,file={url}]"
        return text.replace("[sticker]", cq_code).strip()

    # ---- WebSocket 回复（含多段拆分） ----

    async def _reply(self, event: dict, text: str):
        """通过 WebSocket 发送回复（自然拆分 + 打字延迟）"""
        if not self._ws:
            logger.warning("WebSocket 未连接，无法发送回复")
            return

        import re
        import random
        # 将 [face:ID] 转为 QQ 表情 CQ 码
        text = re.sub(r'\[face:(\d+)\]', r'[CQ:face,id=\1]', text)

        msg_type = event.get("message_type", "private")
        user_id = event.get("user_id")
        self._msg_id += 1

        # 带格式的文字一条发完，不拆分不延迟
        has_bullets = "  /" in text or "🎭" in text or "☀️" in text or "🔧" in text or "├─" in text or "📋" in text
        if has_bullets:
            segs = [text]
        else:
            text = text.replace('\n', '')
            delay = min(0.3 + len(text) * 0.008, 2.0) * random.uniform(0.8, 1.2)
            await asyncio.sleep(delay)
            segs = self._split_message(text)

        for i, seg in enumerate(segs):
            final_text = seg

            # 首段群聊加 @
            if i == 0 and msg_type == "group" and user_id and not seg.startswith("[CQ:at"):
                final_text = f"[CQ:at,qq={user_id}] {seg}"

            action = {
                "action": "send_msg",
                "params": {
                    "message_type": msg_type,
                    "message": final_text,
                },
                "echo": f"reply_{self._msg_id}",
            }

            if msg_type == "group":
                action["params"]["group_id"] = event.get("group_id")
            else:
                action["params"]["user_id"] = user_id

            try:
                await self._ws.send(json.dumps(action))
            except Exception as e:
                logger.error("WebSocket 发送消息失败: %s", e)
                return

            # 片段之间停顿 0.6-1.2 秒，模拟思考节奏
            if i < len(segs) - 1:
                await asyncio.sleep(0.6 + (i * 0.2))

    # ---- 角色管理 ----

    async def _cmd_addchar(self, bind_key: str, event: dict):
        """添加角色指引"""
        await self._reply(event, (
            "添加角色方法:\n"
            "1. 在服务器上运行: python add_character.py --template -n \"角色名\" -s \"出处\"\n"
            "2. 手动编辑生成的 JSON 文件\n"
            "3. 管理员用 /reload 加载\n"
            "或直接编辑 characters/ 目录下的 JSON 文件"
        ))

    async def _cmd_removechar(self, bind_key: str, arg: str, event: dict):
        """删除角色（管理员）"""
        user_id_num = bind_key.replace("private_", "").replace("group_", "")
        if not self.engine.profile_mgr.is_admin(user_id_num):
            await self._reply(event, "你没有权限执行此操作。")
            return
        if not arg:
            await self._reply(event, "用法: /removechar <角色名>")
            return

        chars = self.engine.char_mgr.list_characters()
        matched = None
        for c in chars:
            if arg == c["id"] or arg == c["name"]:
                matched = c
                break
        if not matched:
            await self._reply(event, f"未找到角色「{arg}」")
            return

        import os
        from pathlib import Path
        filepath = Path(self.engine.char_mgr._dir) / f"{matched['id']}.json"
        if filepath.exists():
            os.remove(filepath)
            self.engine.char_mgr.reload()
            await self._reply(event, f"已删除角色「{matched['name']}」")
        else:
            await self._reply(event, "角色文件不存在")

    @staticmethod
    @staticmethod
    def _split_message(text: str) -> list[str]:
        """按自然句子拆分，模拟真人分段说话"""
        import re
        # 先处理显式的 [pause] 标记
        if "[pause]" in text:
            parts = [p.strip() for p in text.split("[pause]") if p.strip()]
            # 每段再按句子拆分
            result = []
            for p in parts:
                result.extend(QQBotServer._split_sentences(p))
            return [r for r in result if r] if result else [text]

        # 无 [pause] 时按句子拆分
        sentences = QQBotServer._split_sentences(text)
        # 如果拆完后只有一段或一段非常短，就不拆了
        if len(sentences) <= 1 or len(text) < 30:
            return [text]
        # 太短的分句和前一句合并
        merged = []
        for s in sentences:
            if merged and len(s) < 6:
                merged[-1] += s
            else:
                merged.append(s)
        return merged if len(merged) > 1 else [text]

    @staticmethod
    def _split_sentences(text: str) -> list[str]:
        """按句号、问号、感叹号、省略号拆句子"""
        import re
        # 在 [CQ:...] 内部不拆分
        parts = re.split(r'(?<=[。？！……!?])(?![^\[]*\])', text)
        return [p.strip() for p in parts if p.strip()]

    # ---- 主动对话 ----

    async def _store_event(self, bind_key: str, event: dict):
        """保存最新事件，用于主动对话时发消息"""
        self._last_events[bind_key] = event

    async def _proactive_loop(self):
        """后台定期检查：长时间没说话的，主动找话题"""
        import random
        from datetime import datetime, timedelta

        await asyncio.sleep(self._proactive_check)  # 先等一轮再开始

        while True:
            try:
                now = datetime.now()
                threshold = timedelta(seconds=self._proactive_interval)

                # 遍历所有有绑定的会话（只对私聊生效）
                for bind_key, event in list(self._last_events.items()):
                    if bind_key.startswith("group_"):
                        continue  # 群聊不主动说话
                    char_id = self._get_user_character(bind_key)
                    if not char_id or not self._ws:
                        continue

                    card = self.engine.char_mgr.get_character(char_id)
                    if not card:
                        continue

                    profile = self.engine.profile_mgr.get_or_create_profile(bind_key)
                    cmem = profile.get_or_create_char_memory(char_id)

                    # 检查最后活动时间
                    if not cmem.last_message_at:
                        continue
                    last_time = datetime.fromisoformat(cmem.last_message_at)
                    idle_time = now - last_time

                    if idle_time < threshold:
                        continue

                    # 找一句合适的台词主动发送
                    lines = card.source_dialogues or []
                    if lines:
                        msg = random.choice(lines)
                        event["raw_message"] = msg
                        event["message"] = msg
                        name = card.name

                        # 直接发送
                        await self._reply(event, f"{name}: {msg}")
                        logger.info("主动对话 user=%s char=%s: %s", bind_key, char_id, msg[:30])

                        # 更新活动时间避免重复触发
                        cmem.last_message_at = now.isoformat()

            except Exception as e:
                logger.error("主动对话检查异常: %s", e)

            await asyncio.sleep(self._proactive_check)

    # ---- 辅助 ----

    @staticmethod
    def _get_bind_key(event: dict) -> str:
        """生成绑定键：私聊用 private_QQ号，群聊用 group_群号"""
        msg_type = event.get("message_type", "private")
        if msg_type == "group":
            group_id = event.get("group_id", "")
            return f"group_{group_id}" if group_id else ""
        return f"private_{event.get('user_id', '')}"

    def _get_user_character(self, bind_key: str) -> Optional[str]:
        """获取绑定键对应的角色"""
        return self.engine.profile_mgr.get_binding(bind_key)

    def _set_user_character(self, bind_key: str, character_id: str):
        """持久化绑定"""
        self.engine.profile_mgr.set_binding(bind_key, character_id)

    async def _send_switch_greeting(self, event: dict, character_id: str):
        """切换角色后，用角色自己的话打招呼"""
        import random
        card = self.engine.char_mgr.get_character(character_id)
        if not card:
            return

        name = card.name
        lines = card.source_dialogues or []

        if lines:
            # 从台词库挑一句像打招呼的话
            greetings = [l for l in lines if any(kw in l for kw in ["你好", "你好", "早上", "请多", "来了", "初次", "新来的", name[:2], "熊熊", "队长"])]
            if not greetings:
                greetings = lines[:3]
            reply = f"{name}: {random.choice(greetings)}"
        elif card.greeting_style:
            reply = f"{name}: {card.greeting_style[:80]}"
        else:
            reply = f"已切换至{name}，开始对话吧。"

        await self._reply(event, reply)

    def _extract_message(self, event: dict) -> tuple[str, str]:
        """从事件中提取文字消息和表情描述（支持 VL 视觉理解）"""
        raw = (event.get("raw_message", "") or "").strip()
        msg = event.get("message", "")
        sticker_text = ""

        # 尝试从 message list 中提取图片 URL
        if isinstance(msg, list):
            parts = []
            for seg in msg:
                if not isinstance(seg, dict):
                    continue
                seg_type = seg.get("type", "")
                seg_data = seg.get("data", {}) or {}

                if seg_type == "text":
                    parts.append(seg_data.get("text", ""))
                elif seg_type == "mface":
                    name = seg_data.get("name", seg_data.get("text", ""))
                    # 尝试用 VL API 理解表情包
                    url = seg_data.get("url", "")
                    desc = self._describe_image(url) if url else ""
                    sticker_text = f"[发送了{name}表情包: {desc}]" if desc else f"[发送了{name}表情包]"
                elif seg_type == "image":
                    url = seg_data.get("url", "")
                    desc = self._describe_image(url) if url else ""
                    sticker_text = desc if desc else "[发送了一张图片]"
                elif seg_type == "face":
                    if not sticker_text:
                        sticker_text = "[表情]"

            if parts and not raw:
                raw = "".join(parts)

        return raw, sticker_text

    def _describe_image(self, url: str) -> str:
        """调用多模态 API 描述图片内容"""
        if not url or len(url) < 10:
            return ""
        try:
            cfg = get_config().llm
            api_key = cfg.get("api_key", "")
            base_url = cfg.get("base_url", "https://api.openai.com/v1").rstrip("/")

            with httpx.Client(base_url=base_url, timeout=30.0, headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            }) as client:
                resp = client.post("/chat/completions", json={
                    "model": cfg.get("model", "qwen-vl-plus"),
                    "messages": [
                        {"role": "user", "content": [
                            {"type": "text", "text": "用一句话描述这个图片/表情包的内容和情绪"},
                            {"type": "image_url", "image_url": {"url": url}},
                        ]},
                    ],
                    "max_tokens": 100,
                })
                if resp.status_code == 200:
                    return resp.json()["choices"][0]["message"]["content"].strip()
        except Exception as e:
            logger.debug("VL 描述失败: %s", e)
        return ""

    # ---- MCP 工具集成 ----

    async def _mcp_search(self, query: str) -> str:
        """网络搜索工具"""
        import urllib.parse
        try:
            url = f"https://api.duckduckgo.com/?q={urllib.parse.quote(query)}&format=json&no_html=1"
            async with httpx.AsyncClient(timeout=10.0) as c:
                resp = await c.get(url)
                if resp.status_code == 200:
                    data = resp.json()
                    abstract = data.get("AbstractText", "")
                    if abstract:
                        return abstract[:300]
                    related = data.get("RelatedTopics", [])
                    if related:
                        return related[0].get("Text", "")[:300]
            return ""
        except Exception as e:
            logger.debug("搜索失败: %s", e)
            return ""

    @staticmethod
    def _extract_message_old(event: dict) -> tuple[str, str]:
        raw = (event.get("raw_message", "") or "").strip()
        msg = event.get("message", "")
        sticker_text = ""

        # 如果 message 是列表格式，从中提取 sticker 信息
        if isinstance(msg, list):
            parts = []
            for seg in msg:
                if not isinstance(seg, dict):
                    continue
                seg_type = seg.get("type", "")
                seg_data = seg.get("data", {}) or {}

                if seg_type == "text":
                    parts.append(seg_data.get("text", ""))
                elif seg_type == "mface":
                    name = seg_data.get("name", seg_data.get("text", ""))
                    sticker_text = f"[发送了{name}表情包]"
                elif seg_type == "image":
                    if not sticker_text:
                        sticker_text = "[发送了一张图片]"
                elif seg_type == "face":
                    if not sticker_text:
                        sticker_text = "[表情]"

            if parts and not raw:
                raw = "".join(parts)

        return raw, sticker_text

    @staticmethod
    def _clean_message(text: str) -> str:
        """将 CQ 码转为文字描述，让 AI 理解表情包和图片"""
        import re
        # 表情包/大表情 [CQ:mface,id=xxx,text=名称]
        text = re.sub(r'\[CQ:mface[^\]]*text=([^,\]]+)[^\]]*\]', r'[发送了\1表情包]', text)
        # 图片 [CQ:image,...]
        text = re.sub(r'\[CQ:image[^\]]*\]', '[发送了一张图片]', text)
        # QQ 小表情 [CQ:face,id=xxx]
        text = re.sub(r'\[CQ:face,id=\d+\]', '[表情]', text)
        # 其他 CQ 码
        text = re.sub(r'\[CQ:[^\]]*\]', '', text)
        return text.strip()

    @staticmethod
    def _is_at_bot(event: dict) -> bool:
        """检查群消息是否 @了机器人"""
        message = event.get("message", "")
        if isinstance(message, list):
            for seg in message:
                if isinstance(seg, dict) and seg.get("type") == "at":
                    return True
            return False
        if isinstance(message, str):
            import re
            return bool(re.match(r'^\[CQ:at,qq=(?:\d+|all)\]', message.strip()))
        return False

    @staticmethod
    def _strip_at(text: str) -> str:
        """去除消息开头的 @ 前缀"""
        import re
        return re.sub(r'^\[CQ:at,qq=\d+\]\s*', '', text).strip()
