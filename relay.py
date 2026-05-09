"""
Echo_Bot 本地消息转发器

在你这台电脑上运行，作为 LLOneBot 和云服务器之间的桥梁。
服务器断线时自动缓存消息，恢复后补发。

用法：
  1. LLOneBot 设置反向 WebSocket 为 ws://127.0.0.1:8767
  2. 在此电脑上运行：python relay.py
  3. 转发器会把消息发到云服务器 ws://47.82.121.4:8765

原理：
  LLOneBot → 本地转发器 (ws://127.0.0.1:8767)
                   ↓ 自动重连 + 缓存
             云服务器 (ws://47.82.121.4:8765)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import websockets

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("relay")

# 云服务器地址
SERVER_URL = "ws://47.82.121.4:8765"
# 本地监听端口（LLOneBot 连这个）
LOCAL_PORT = 8767
# 缓存文件路径
CACHE_FILE = "relay_cache.jsonl"


class Relay:
    """消息转发器"""

    def __init__(self):
        self.server_ws: Optional[websockets.WebSocketClientProtocol] = None
        self.server_connected = False
        self.cache: list[dict] = []

        # 加载未发送的缓存
        self._load_cache()

    def _load_cache(self):
        if not os.path.exists(CACHE_FILE):
            return
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        self.cache.append(json.loads(line))
            if self.cache:
                logger.info("加载 %d 条缓存消息", len(self.cache))
        except Exception as e:
            logger.error("加载缓存失败: %s", e)

    def _save_to_cache(self, event: dict):
        try:
            with open(CACHE_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.error("写入缓存失败: %s", e)

    def _clear_cache(self):
        try:
            if os.path.exists(CACHE_FILE):
                os.remove(CACHE_FILE)
            self.cache = []
        except Exception as e:
            logger.error("清理缓存失败: %s", e)

    async def connect_server(self):
        """连接到云服务器（自动重连）"""
        while True:
            try:
                self.server_ws = await websockets.connect(
                    SERVER_URL,
                    ping_interval=30,
                    ping_timeout=10,
                    max_size=2 ** 20,
                )
                self.server_connected = True
                logger.info("已连接到云服务器")

                # 连上后立即发送缓存的离线消息
                if self.cache:
                    logger.info("补发 %d 条缓存消息...", len(self.cache))
                    for event in self.cache:
                        try:
                            await self.server_ws.send(json.dumps(event))
                            await asyncio.sleep(0.3)  # 间隔，避免刷屏
                        except Exception:
                            logger.warning("补发失败，保留剩余缓存")
                            break
                    else:
                        self._clear_cache()
                        logger.info("缓存消息全部补发完成")

                # 维持连接
                async for _ in self.server_ws:
                    pass  # 等待断开

            except Exception as e:
                logger.warning("云服务器连接失败: %s，30秒后重试", e)
            finally:
                self.server_connected = False
                self.server_ws = None

            await asyncio.sleep(30)

    async def handle_local(self, ws):
        """处理来自 LLOneBot 的消息"""
        async for raw in ws:
            try:
                event = json.loads(raw)
            except json.JSONDecodeError:
                continue

            # 忽略心跳
            if event.get("post_type") == "meta_event":
                continue

            # 转发到云服务器
            if self.server_connected and self.server_ws:
                try:
                    await self.server_ws.send(raw)
                except Exception:
                    self._save_to_cache(event)
                    logger.info("服务器暂时不可用，消息已缓存")
            else:
                self._save_to_cache(event)
                logger.info("服务器未连接，消息已缓存")

    async def start(self):
        """启动转发器"""
        # 启动服务器连接任务
        asyncio.ensure_future(self.connect_server())

        # 启动本地 WebSocket 服务器（LLOneBot 连这里）
        logger.info("启动本地转发器: ws://0.0.0.0:%d", LOCAL_PORT)
        logger.info("请在 LLOneBot 中设置反向 WebSocket: ws://127.0.0.1:%d", LOCAL_PORT)

        async with websockets.serve(
            self.handle_local,
            "0.0.0.0",
            LOCAL_PORT,
            ping_interval=30,
            ping_timeout=10,
            max_size=2 ** 20,
        ):
            await asyncio.Future()  # 永久运行


def main():
    print(f"\n  Echo_Bot 本地消息转发器")
    print(f"  {'='*40}")
    print(f"  本地监听: ws://0.0.0.0:{LOCAL_PORT}")
    print(f"  转发目标: {SERVER_URL}")
    print(f"  缓存文件: {CACHE_FILE}")
    print(f"  {'='*40}\n")

    relay = Relay()
    asyncio.run(relay.start())


if __name__ == "__main__":
    main()
