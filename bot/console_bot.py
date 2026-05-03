"""
终端测试机器人：在命令行中与 AI 角色对话

用途：开发调试，无需 QQ 环境即可测试整个系统
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Optional

from core.engine import DialogueEngine
from core.models import CharacterCard

logger = logging.getLogger(__name__)


class ConsoleBot:
    """
    命令行对话界面

    支持：
    - 选择角色
    - 多轮对话
    - 查看用户画像
    - 切换角色
    """

    def __init__(self, engine: DialogueEngine):
        self.engine = engine
        self.current_user_id = "test_user_001"
        self.current_char_id: Optional[str] = None
        self.current_char: Optional[CharacterCard] = None
        self.running = True

    # ---- 主循环 ----

    async def run(self):
        """启动控制台界面"""
        self._print_banner()

        # 选择角色
        if not await self._select_character():
            return

        while self.running:
            try:
                user_input = await self._get_input()
                if not user_input:
                    continue

                # 处理命令
                if user_input.startswith("/"):
                    await self._handle_command(user_input)
                    continue

                # 发送消息
                await self._send_message(user_input)

            except KeyboardInterrupt:
                print("\n\n再见！")
                break
            except Exception as e:
                logger.error("处理消息异常: %s", e)
                print(f"\n[错误] {e}\n")

    # ---- 消息处理 ----

    async def _send_message(self, text: str):
        """发送消息并显示回复"""
        try:
            reply, memory = await self.engine.process_message(
                user_message=text,
                user_id=self.current_user_id,
                character_id=self.current_char_id,
            )

            print(f"\n{self.current_char.name}: {reply}\n")

            # 调试模式：显示 MEMORY 摘要
            if memory:
                mood = memory.get("observations", {}).get("mood", "?")
                stage = memory.get("relationship", {}).get("current_stage", "?")
                tone = memory.get("strategy_adjustments", {}).get("next_tone", "")
                print(f"  [MEMORY] 情绪={mood} 关系={stage} 语气建议={tone}")

        except Exception as e:
            print(f"\n[回复失败] {e}\n")

    # ---- 命令处理 ----

    async def _handle_command(self, cmd: str):
        cmd = cmd.strip().lower()

        if cmd in ("/quit", "/exit", "/q"):
            print("再见！")
            self.running = False

        elif cmd in ("/help", "/h"):
            self._print_help()

        elif cmd.startswith("/switch") or cmd.startswith("/char"):
            await self._select_character()

        elif cmd == "/profile":
            self._show_profile()

        elif cmd == "/roles":
            self._list_characters()

        elif cmd == "/stats":
            self._show_stats()

        elif cmd == "/clear":
            if self.current_char_id:
                self.engine.context_mgr.clear_context(
                    self.current_user_id, self.current_char_id,
                )
                print("对话历史已清空。\n")

        elif cmd == "/history":
            self._show_history()

        else:
            print(f"未知命令: {cmd}，输入 /help 查看帮助\n")

    # ---- 角色选择 ----

    async def _select_character(self) -> bool:
        """选择当前对话角色"""
        chars = self.engine.char_mgr.list_characters()

        if not chars:
            print("没有可用角色。请将角色卡 JSON 放入 characters/ 目录。\n")
            return False

        print("\n可用角色：")
        for i, c in enumerate(chars, 1):
            traits = "、".join(c["traits"]) if c["traits"] else "无标签"
            source = f" [{c['source']}]" if c["source"] else ""
            print(f"  {i}. {c['name']}{source} — {traits}")

        choice = (await asyncio.to_thread(input, "\n输入角色编号或名称（或 q 取消）: ")).strip()

        if choice.lower() in ("q", "quit", ""):
            return False

        selected = None
        # 按编号
        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(chars):
                selected = chars[idx]
        else:
            # 按名称
            for c in chars:
                if choice == c["name"] or choice == c["id"]:
                    selected = c
                    break

        if not selected:
            print("无效选择。\n")
            return False

        self.current_char_id = selected["id"]
        self.current_char = self.engine.char_mgr.get_character(selected["id"])

        print(f"\n=== 切换到角色: {self.current_char.name} ===\n")
        if self.current_char.first_meeting:
            print(f"[开场白] {self.current_char.first_meeting}\n")

        return True

    # ---- 信息显示 ----

    def _show_profile(self):
        """显示当前用户画像"""
        profile = self.engine.profile_mgr.get_or_create_profile(self.current_user_id)
        char_memory = profile.get_or_create_char_memory(self.current_char_id)

        print("\n=== 用户画像 ===")
        print(f"  用户ID: {profile.user_id}")
        print(f"  对话轮数: {char_memory.conversation_count}")
        print(f"  关系阶段: {char_memory.relationship_stage}")
        print(f"  信任度: {char_memory.trust_level}/10")
        print(f"  好感度: {char_memory.affection_level}/10")
        if char_memory.observed_traits:
            print(f"  性格标签: {'、'.join(char_memory.observed_traits)}")
        if char_memory.observed_interests:
            print(f"  兴趣: {'、'.join(char_memory.observed_interests)}")
        if char_memory.observed_dislikes:
            print(f"  反感: {'、'.join(char_memory.observed_dislikes)}")
        if char_memory.last_summary:
            print(f"  最近摘要: {char_memory.last_summary[:100]}")
        print()

    def _list_characters(self):
        """列出所有角色"""
        chars = self.engine.char_mgr.list_characters()
        print("\n=== 角色列表 ===")
        for c in chars:
            marker = " <当前" if c["id"] == self.current_char_id else ""
            print(f"  [{c['id']}] {c['name']}{marker}")
        print()

    def _show_stats(self):
        """显示运行统计"""
        print("\n=== 运行统计 ===")
        print(f"  API 调用次数: {self.engine.total_calls}")
        print(f"  错误次数: {self.engine.total_errors}")
        sessions = self.engine.context_mgr.get_all_active_sessions()
        print(f"  活跃会话: {len(sessions)}")
        for uid, cid in sessions:
            size = self.engine.context_mgr.get_context_size(uid, cid)
            char = self.engine.char_mgr.get_character(cid)
            name = char.name if char else cid
            print(f"    {name} ({uid}): {size} 轮")
        print()

    def _show_history(self):
        """显示当前对话历史"""
        if not self.current_char_id:
            print("请先选择角色。\n")
            return
        turns = self.engine.context_mgr.get_recent_turns(
            self.current_user_id, self.current_char_id, 10,
        )
        if not turns:
            print("暂无对话历史。\n")
            return
        print(f"\n=== 最近 {len(turns)} 轮对话 ===")
        for t in turns:
            role = "你" if t.role == "user" else self.current_char.name if self.current_char else "AI"
            content = t.content[:150]
            print(f"  [{role}] {content}")
        print()

    # ---- 辅助 ----

    def _print_banner(self):
        print("=" * 50)
        print("    QQ AI Bot — 终端测试模式")
        print("    输入 /help 查看命令")
        print("=" * 50)
        print()

    def _print_help(self):
        print("""
可用命令：
  /switch, /char   切换角色
  /profile         查看当前用户画像
  /roles           列出所有角色
  /stats           运行统计
  /history         最近对话历史
  /clear           清空对话上下文
  /quit, /exit     退出
  /help            显示帮助

直接输入文本开始对话。
""")

    async def _get_input(self) -> str:
        """获取用户输入"""
        prefix = f"{self.current_char.name if self.current_char else '?'}> "
        return (await asyncio.to_thread(input, prefix)).strip()
