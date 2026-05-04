"""
QQ AI Bot — 主入口

使用方式：
  # 终端测试（开发用）
  python main.py

  # 生产部署（QQ 模式，需 go-cqhttp）
  python main.py --bot server

  # 指定配置文件
  python main.py --bot server --config prod.yml

环境变量：
  AIBOT_LLM__API_KEY=sk-xxx     API Key（推荐用此方式，避免硬编码）
  AIBOT_LLM__PROVIDER=deepseek  厂商预设: deepseek / moonshot / qwen / openai
  AIBOT_LLM__BASE_URL=...       自定义 API 地址
  AIBOT_LLM__MODEL=...          模型名
  HTTP_PROXY=http://127.0.0.1:7890   HTTP 代理（访问外网 API 时使用）
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

_project_root = Path(__file__).parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

logger = logging.getLogger(__name__)


def setup_logging(level: str = "INFO", log_file: str | None = None):
    """配置日志"""
    handlers = [logging.StreamHandler(sys.stdout)]
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(RotatingFileHandler(
            log_file, maxBytes=10*1024*1024, backupCount=5, encoding="utf-8",
        ))

    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=handlers,
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("websockets").setLevel(logging.WARNING)


async def run_console_mode(config_path: str | None = None):
    """终端测试模式"""
    from config import load_config
    from core.character_manager import CharacterManager
    from core.engine import DialogueEngine
    from core.llm_client import create_llm_client
    from core.profile_manager import ProfileManager
    from bot.console_bot import ConsoleBot

    cfg = load_config(config_path)
    logger.info("配置加载完成: %s", cfg)

    char_mgr = CharacterManager(cfg.paths["characters_dir"])
    if not char_mgr.list_characters():
        logger.warning("characters/ 目录为空，请添加角色卡 JSON 文件")

    profile_mgr = ProfileManager(cfg.paths["db_path"])
    llm = create_llm_client()
    engine = DialogueEngine(char_mgr, profile_mgr, llm)

    bot = ConsoleBot(engine)
    logger.info("启动终端测试模式")
    await bot.run()


async def run_server_mode(config_path: str | None = None):
    """QQ 机器人服务模式 — 对接 go-cqhttp"""
    from config import load_config
    from core.character_manager import CharacterManager
    from core.engine import DialogueEngine
    from core.llm_client import create_llm_client
    from core.profile_manager import ProfileManager
    from bot.server_bot import QQBotServer

    cfg = load_config(config_path)
    logger.info("配置加载完成: %s", cfg)

    char_mgr = CharacterManager(cfg.paths["characters_dir"])
    if not char_mgr.list_characters():
        logger.warning("characters/ 目录为空！")

    profile_mgr = ProfileManager(cfg.paths["db_path"])
    llm = create_llm_client()
    engine = DialogueEngine(char_mgr, profile_mgr, llm)

    svr_cfg = cfg.server
    server = QQBotServer(
        engine=engine,
        host=svr_cfg.get("host", "0.0.0.0"),
        ws_port=svr_cfg.get("ws_port", 8765),
    )

    logger.info("启动 QQ 机器人服务模式")
    print(f"\n  WS 服务器: ws://{svr_cfg.get('host', '0.0.0.0')}:{svr_cfg.get('ws_port', 8765)}")
    print(f"  加载角色: {len(char_mgr.list_characters())} 个\n")
    print("等待 LLOneBot 连接...\n")

    await server.start()


def parse_args():
    parser = argparse.ArgumentParser(
        description="QQ AI Bot — 角色扮演聊天机器人",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
环境变量：
  AIBOT_LLM__API_KEY=sk-xxx      API Key（推荐）
  AIBOT_LLM__PROVIDER=deepseek   厂商预设
  HTTP_PROXY=http://127.0.0.1:7890  代理
        """,
    )
    parser.add_argument(
        "--config", "-c", default=None,
        help="配置文件路径（默认: config.yml）",
    )
    parser.add_argument(
        "--bot", "-b",
        choices=["console", "server"],
        default="console",
        help="运行模式: console=终端测试, server=QQ 机器人服务（默认: console）",
    )
    parser.add_argument(
        "--log-level", "-l",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="日志级别",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    setup_logging(level=args.log_level)

    from config import load_config
    cfg = load_config(args.config)

    # 最终日志配置
    log_level = cfg.logging_cfg.get("level", args.log_level)
    log_file = cfg.logging_cfg.get("file")
    setup_logging(level=log_level, log_file=log_file)

    logger.info("=" * 48)
    logger.info("QQ AI Bot 启动")
    logger.info("模式: %s", args.bot)
    logger.info("AI 提供方: %s  (%s)", cfg.llm.get("provider"), cfg.llm.get("model"))

    if args.bot == "server":
        asyncio.run(run_server_mode(args.config))
    else:
        asyncio.run(run_console_mode(args.config))

    logger.info("QQ AI Bot 正常退出")


if __name__ == "__main__":
    main()
