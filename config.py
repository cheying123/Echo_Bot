"""
配置管理：支持 YAML + 环境变量 + .env 文件
"""

import os
from pathlib import Path
from typing import Optional

import yaml

# ===================================================================
# 国内 AI API 厂商预设
# ===================================================================

AI_PROVIDER_PRESETS = {
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
    },
    "deepseek": {
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
    },
    "moonshot": {
        "base_url": "https://api.moonshot.cn/v1",
        "model": "moonshot-v1-8k",
    },
    "qwen": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-plus",
    },
    "hunyuan": {
        "base_url": "https://api.hunyuan.cloud.tencent.com/v1",
        "model": "hunyuan-standard",
    },
    "spark": {
        "base_url": "https://spark-api-open.xf-yun.com/v1",
        "model": "4.0Ultra",
    },
    "ernie": {
        "base_url": "https://aip.baidubce.com/rpc/2.0/ai_custom/v1/wenxinworkshop/chat",
        "model": "ernie-4.0",
    },
    "ollama": {
        "base_url": "http://localhost:11434",
        "model": "qwen2.5:7b",
    },
}

# ===================================================================
# 默认配置
# ===================================================================

DEFAULT_CONFIG = {
    # ---- LLM API ----
    "llm": {
        "provider": "openai",
        "api_key": "",
        "base_url": "",
        "model": "",
        "temperature": 0.8,
        "max_tokens": 1024,
        "timeout": 60,
        # 代理设置
        "proxy": {
            "http": "",   # e.g. http://127.0.0.1:7890
            "https": "",
        },
        # 重试设置
        "retry": {
            "max_retries": 3,
            "base_delay": 1.0,  # 秒
            "max_delay": 30.0,
        },
    },
    # ---- 记忆系统 ----
    "memory": {
        "short_term_rounds": 8,
        "summary_interval": 10,
        "memory_extraction_interval": 1,
        "monthly_rebuild_interval_days": 30,
    },
    # ---- 对话 ----
    "dialogue": {
        "max_response_length": 100,
        "enable_action_description": True,
    },
    # ---- 安全 ----
    "security": {
        "forbidden_keywords": [
            "你是AI", "你是一个AI", "语言模型", "assistant",
            "系统提示词", "system prompt", "你被设定为",
        ],
        "enable_content_filter": True,
    },
    # ---- 服务器（go-cqhttp 反向 WS 模式） ----
    "server": {
        "host": "0.0.0.0",
        "ws_port": 8765,
        "http_api_url": "http://127.0.0.1:5700",
        "http_api_token": "",
    },
    # ---- 数据路径 ----
    "paths": {
        "characters_dir": "characters",
        "data_dir": "data",
        "db_path": "data/bot.db",
    },
    # ---- 日志 ----
    "logging": {
        "level": "INFO",
        "file": "data/bot.log",
    },
}


# ===================================================================
# 配置加载器
# ===================================================================

class Config:
    """全局配置"""

    def __init__(self, config_path: Optional[str] = None):
        self._data = self._deep_copy(DEFAULT_CONFIG)
        self._config_dir: Optional[Path] = None

        # 0) 确定项目根目录（config.py 所在目录的父目录 = 项目根）
        _script_dir = Path(__file__).resolve().parent
        _project_root = _script_dir  # config.py 在项目根目录

        # 1) 加载 .env 文件
        self._load_dotenv()

        # 2) YAML 配置文件（优先指定路径，其次 CWD，最后项目目录）
        if config_path:
            self._load_yaml(Path(config_path))
        else:
            searched = []
            for candidate in ["config.yml", "config.yaml", "config.local.yml"]:
                # 先搜 CWD
                p = Path(candidate)
                if p.exists():
                    self._load_yaml(p)
                    break
                searched.append(str(p))
                # 再搜项目目录
                p2 = _project_root / candidate
                if p2.exists():
                    self._load_yaml(p2)
                    break
                searched.append(str(p2))
            else:
                # 所有路径都没找到，但可能通过 .env 配好了，不报错
                pass

        # 3) 环境变量覆盖

        # 3) 环境变量覆盖
        self._apply_env_overrides()

        # 4) 填充 AI 厂商预设（如果 base_url/model 为空）
        self._apply_provider_preset()

        # 5) 解析路径
        self._resolve_paths()

    # ---- 属性访问 ----

    @property
    def llm(self) -> dict:
        return self._data["llm"]

    @property
    def memory(self) -> dict:
        return self._data["memory"]

    @property
    def dialogue(self) -> dict:
        return self._data["dialogue"]

    @property
    def security(self) -> dict:
        return self._data["security"]

    @property
    def server(self) -> dict:
        return self._data["server"]

    @property
    def paths(self) -> dict:
        return self._data["paths"]

    @property
    def logging_cfg(self) -> dict:
        return self._data["logging"]

    # ---- 内部方法 ----

    def _load_dotenv(self):
        """尝试加载 .env 文件（优先 CWD，其次项目目录）"""
        try:
            from dotenv import load_dotenv
            loaded = load_dotenv()  # CWD
            if not loaded:
                _script_dir = Path(__file__).resolve().parent
                load_dotenv(_script_dir / ".env")  # 项目目录
        except ImportError:
            pass

    def _load_yaml(self, path: Path):
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                user_cfg = yaml.safe_load(f) or {}
            self._deep_merge(self._data, user_cfg)
            self._config_dir = path.parent

    def _apply_env_overrides(self):
        """环境变量覆盖，支持 AIBOT_LLM__API_KEY 格式"""
        prefix = "AIBOT_"
        for key, value in os.environ.items():
            if not key.startswith(prefix):
                continue
            parts = key[len(prefix):].lower().split("__")
            target = self._data
            for part in parts[:-1]:
                if part not in target:
                    break
                target = target[part]
            else:
                if parts[-1] in target:
                    target[parts[-1]] = value

    def _apply_provider_preset(self):
        """如果 base_url 或 model 为空，用预设填充"""
        provider = self._data["llm"].get("provider", "openai")
        preset = AI_PROVIDER_PRESETS.get(provider)
        if preset:
            if not self._data["llm"].get("base_url"):
                self._data["llm"]["base_url"] = preset["base_url"]
            if not self._data["llm"].get("model"):
                self._data["llm"]["model"] = preset["model"]

    def _resolve_paths(self):
        # 优先用配置文件所在目录，其次项目根目录，最后 CWD
        _script_dir = Path(__file__).resolve().parent
        base = self._config_dir or _script_dir or Path.cwd()
        for key in ["characters_dir", "data_dir", "db_path"]:
            raw = self._data["paths"][key]
            p = Path(raw)
            if not p.is_absolute():
                p = base / p
            self._data["paths"][key] = str(p.resolve())
        # 日志文件路径同样解析
        log_file = self._data["logging"].get("file", "")
        if log_file:
            p = Path(log_file)
            if not p.is_absolute():
                p = base / p
            self._data["logging"]["file"] = str(p.resolve())

    # ---- 实用方法 ----

    def get(self, *keys: str, default=None):
        target = self._data
        for k in keys:
            if isinstance(target, dict):
                target = target.get(k)
                if target is None:
                    return default
            else:
                return default
        return target

    def get_proxy_dict(self) -> dict:
        """返回 httpx 可用的代理字典"""
        proxy = self._data["llm"].get("proxy", {})
        result = {}
        http_proxy = proxy.get("http", "") or os.environ.get("HTTP_PROXY", "")
        https_proxy = proxy.get("https", "") or os.environ.get("HTTPS_PROXY", "")
        if http_proxy:
            result["http://"] = http_proxy
        if https_proxy:
            result["https://"] = https_proxy
        return result

    def __repr__(self) -> str:
        return (f"Config(provider={self.llm['provider']}, "
                f"model={self.llm['model']}, "
                f"server=ws://{self.server.get('host', '0.0.0.0')}:{self.server.get('ws_port', 8765)})")

    @staticmethod
    def _deep_copy(d: dict) -> dict:
        import copy
        return copy.deepcopy(d)

    @staticmethod
    def _deep_merge(base: dict, overrides: dict):
        for k, v in overrides.items():
            if k in base and isinstance(base[k], dict) and isinstance(v, dict):
                Config._deep_merge(base[k], v)
            elif v is not None:
                base[k] = v


# 全局单例
_config: Optional[Config] = None


def load_config(config_path: Optional[str] = None) -> Config:
    global _config
    _config = Config(config_path)
    return _config


def get_config() -> Config:
    assert _config is not None, "请先调用 load_config()"
    return _config
