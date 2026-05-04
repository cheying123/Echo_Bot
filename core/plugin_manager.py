"""
插件系统：让第三方开发者可以扩展 Echo_Bot 功能

用法：
  1. 在 plugins/ 目录下创建 .py 文件
  2. 继承 Plugin 类，实现钩子方法
  3. 重启即可自动加载

示例插件：
  plugins/hello_world.py
    from core.plugin_manager import Plugin
    class HelloWorldPlugin(Plugin):
        name = "hello"
        description = "示例插件"
        async def on_command(self, cmd, args, event, bind_key):
            if cmd == "hello":
                await self.reply(event, "Hello from plugin!")
                return True
"""

from __future__ import annotations

import importlib
import inspect
import logging
import os
import sys
from pathlib import Path
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


class Plugin:
    """插件基类，所有插件必须继承此类"""

    name: str = "unnamed"
    version: str = "1.0.0"
    description: str = ""
    author: str = ""

    def __init__(self):
        self._reply_fn: Optional[Callable] = None
        self._bot: Any = None  # QQBotServer 实例

    def setup(self, reply_fn: Callable, bot: Any):
        """框架调用，注入依赖"""
        self._reply_fn = reply_fn
        self._bot = bot

    async def reply(self, event: dict, text: str):
        """发送消息（给插件用的快捷方法）"""
        if self._reply_fn:
            await self._reply_fn(event, text)

    # ---- 可覆写的钩子 ----

    async def on_startup(self):
        """服务启动时调用"""
        pass

    async def on_shutdown(self):
        """服务关闭时调用"""
        pass

    async def on_message(self, event: dict, reply: Optional[str]) -> Optional[str]:
        """
        消息处理后调用，可修改回复内容
        返回新的回复文本，或返回 None 不修改
        """
        return reply

    async def on_command(self, cmd: str, args: str, event: dict, bind_key: str) -> Optional[bool]:
        """
        处理自定义命令
        返回 True 表示已处理，False/None 表示不处理
        """
        return None

    def get_commands(self) -> list[dict]:
        """返回插件支持的命令列表，用于 /help"""
        return []


class PluginManager:
    """插件加载器"""

    def __init__(self, plugins_dir: str = "plugins"):
        self._dir = Path(plugins_dir)
        self._dir.mkdir(exist_ok=True)
        self.plugins: list[Plugin] = []

        # 确保插件目录在 sys.path 中
        plugin_path = str(self._dir.resolve())
        if plugin_path not in sys.path:
            sys.path.insert(0, plugin_path)

    def load_all(self):
        """扫描 plugins/ 目录加载所有插件"""
        if not self._dir.exists():
            logger.warning("插件目录不存在: %s", self._dir)
            return

        for pyfile in sorted(self._dir.glob("*.py")):
            if pyfile.name.startswith("_"):
                continue
            try:
                self._load_plugin(pyfile)
            except Exception as e:
                logger.error("加载插件失败 %s: %s", pyfile.name, e)

        logger.info("插件加载完成: %d 个插件", len(self.plugins))

    def _load_plugin(self, path: Path):
        """加载单个插件文件"""
        module_name = path.stem
        spec = importlib.util.spec_from_file_location(module_name, path)

        if spec is None or spec.loader is None:
            raise ImportError(f"无法加载 {path}")

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        # 查找模块中所有 Plugin 子类
        for name, cls in inspect.getmembers(module, inspect.isclass):
            if issubclass(cls, Plugin) and cls is not Plugin:
                plugin = cls()
                self.plugins.append(plugin)
                logger.info("  加载插件: %s v%s - %s", plugin.name, plugin.version, plugin.description)
                return

        raise ImportError(f"{path.name} 中未找到 Plugin 子类")

    def get_plugin(self, name: str) -> Optional[Plugin]:
        """按名称查找插件"""
        for p in self.plugins:
            if p.name == name:
                return p
        return None

    async def dispatch_startup(self):
        for p in self.plugins:
            try:
                await p.on_startup()
            except Exception as e:
                logger.error("插件 on_startup 异常 %s: %s", p.name, e)

    async def dispatch_shutdown(self):
        for p in self.plugins:
            try:
                await p.on_shutdown()
            except Exception as e:
                logger.error("插件 on_shutdown 异常 %s: %s", p.name, e)

    async def dispatch_message(self, event: dict, reply: Optional[str]) -> Optional[str]:
        """消息钩子链，每个插件可以修改回复"""
        current = reply
        for p in self.plugins:
            try:
                result = await p.on_message(event, current)
                if result is not None:
                    current = result
            except Exception as e:
                logger.error("插件 on_message 异常 %s: %s", p.name, e)
        return current

    async def dispatch_command(self, cmd: str, args: str, event: dict, bind_key: str) -> bool:
        """命令钩子链，插件优先处理"""
        for p in self.plugins:
            try:
                if await p.on_command(cmd, args, event, bind_key):
                    return True
            except Exception as e:
                logger.error("插件 on_command 异常 %s: %s", p.name, e)
        return False

    def get_all_commands(self) -> list[dict]:
        """收集所有插件的命令列表"""
        cmds = []
        for p in self.plugins:
            cmds.extend(p.get_commands())
        return cmds
