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
from typing import Optional

import websockets
from websockets.server import WebSocketServer

from core.engine import DialogueEngine

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

        # 消息 ID 自增（用于 echo）
        self._msg_id = 0

        # 当前 WebSocket 连接
        self._ws: Optional[websockets.WebSocketServerProtocol] = None

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
            await asyncio.Future()  # 永久运行

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
        raw_message = (event.get("raw_message", "") or event.get("message", "")).strip()

        if not raw_message or not bind_key:
            return

        # ---- 系统命令（群聊中斜杠命令不需要 @） ----
        if raw_message.startswith("/"):
            if msg_type == "group":
                raw_message = self._strip_at(raw_message)
            await self._handle_command(raw_message, bind_key, event)
            return

        # ---- 群聊 @ -> AI 回复 ----
        if msg_type == "group":
            if not self._is_at_bot(event):
                return
            raw_message = self._strip_at(raw_message)

        character_id = self._get_user_character(bind_key)
        if not character_id:
            hint = "你还没有绑定角色，请发送 /roles 查看可用角色，/switch <角色名> 选择。"
            if msg_type == "group":
                hint = "@我 " + hint
            await self._reply(event, hint)
            return

        # 调用引擎
        try:
            # 群聊用 group_群号 作为记忆隔离 key，私聊用 QQ 号
            memory_user = bind_key if msg_type == "group" else user_id
            reply, memory = await self.engine.process_message(
                user_message=raw_message,
                user_id=memory_user,
                character_id=character_id,
            )
            if reply:
                await self._reply(event, reply)
        except Exception as e:
            logger.error("处理消息异常 user=%s: %s", user_id, e)
            await self._reply(event, "（暂时无法回应……）")

    # ---- 命令处理 ----

    async def _handle_command(self, cmd: str, bind_key: str, event: dict):
        """处理斜杠命令"""
        cmd = cmd[1:].strip().lower()
        parts = cmd.split(maxsplit=1)
        action = parts[0] if parts else ""
        arg = parts[1] if len(parts) > 1 else ""

        if action in ("switch", "char", "选择"):
            await self._cmd_switch(bind_key, arg, event)
        elif action in ("roles", "角色"):
            await self._cmd_list_roles(event)
        elif action in ("profile", "档案"):
            await self._cmd_profile(bind_key, event)
        elif action in ("status", "状态", "mood"):
            await self._cmd_status(bind_key, event)
        elif action in ("stats", "统计"):
            await self._cmd_stats(bind_key, event)
        elif action == "reload":
            await self._cmd_reload(bind_key, event)
        elif action == "admin":
            await self._cmd_admin(bind_key, arg, event)
        elif action == "help":
            await self._cmd_help(event)
        else:
            await self._reply(event, f"未知命令: /{action}。发送 /help 查看帮助。")

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

    async def _cmd_profile(self, bind_key: str, event: dict):
        profile = self.engine.profile_mgr.get_or_create_profile(bind_key)
        char_id = self._get_user_character(bind_key)
        if not char_id:
            await self._reply(event, "请先绑定角色。")
            return
        cm = profile.get_or_create_char_memory(char_id)
        lines = [
            f"关系阶段: {cm.relationship_stage}",
            f"信任度: {cm.trust_level}/10",
            f"好感度: {cm.affection_level}/10",
            f"对话次数: {cm.conversation_count}",
        ]
        if cm.observed_traits:
            lines.append(f"性格标签: {'、'.join(cm.observed_traits[-5:])}")
        if cm.observed_interests:
            lines.append(f"兴趣: {'、'.join(cm.observed_interests[-5:])}")
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
            "可用命令:\n"
            "  /switch <角色名>  切换当前角色\n"
            "  /roles            查看所有可用角色\n"
            "  /status           查看角色对你的情绪/关系/语气\n"
            "  /profile          查看你的详细画像\n"
            "  /help             显示此帮助\n"
            "\n直接发送消息与当前角色对话即可。\n"
            "首次使用：/roles 查看角色 → /switch 露西亚 选择 → 开始聊天\n"
            "管理员: /admin list / admin add / admin remove\n"
            "       /reload 重新加载角色卡\n"
            "       /stats 查看运行统计"
        ))

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
                "  /admin list            查看管理员列表\n"
                "  /admin add <QQ号>      添加管理员\n"
                "  /admin remove <QQ号>   移除管理员"
            ))

    # ---- WebSocket 回复 ----

    async def _reply(self, event: dict, text: str):
        """通过 WebSocket 发送回复"""
        if not self._ws:
            logger.warning("WebSocket 未连接，无法发送回复")
            return

        msg_type = event.get("message_type", "private")
        user_id = event.get("user_id")
        self._msg_id += 1

        # 构造 OneBot v11 发送消息动作
        action = {
            "action": "send_msg",
            "params": {
                "message_type": msg_type,
                "message": text,
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

    @staticmethod
    def _is_at_bot(event: dict) -> bool:
        """检查群消息是否 @了机器人"""
        message = event.get("message", "")
        if isinstance(message, list):
            for seg in message:
                if isinstance(seg, dict) and seg.get("type") == "at":
                    return True
            return False
        # 字符串格式：检查是否以 CQ at 开头
        if isinstance(message, str):
            import re
            return bool(re.match(r'^\[CQ:at,qq=\d+\]', message.strip()))
        return False  # 无法识别的格式，保守起见不回复

    @staticmethod
    def _strip_at(text: str) -> str:
        """去除消息开头的 @ 前缀"""
        import re
        return re.sub(r'^\[CQ:at,qq=\d+\]\s*', '', text).strip()
