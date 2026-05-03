# Echo_Bot — AI 角色扮演聊天机器人

QQ 聊天机器人，可扮演不同角色与用户对话，学习并记住每个用户的性格、喜好和情绪模式。

## 特性

- **角色扮演** — 任意切换角色，每个角色有独立的性格、说话风格、知识边界
- **记忆系统** — 记住用户的性格特征、兴趣爱好、情绪变化
- **动态适配** — 根据对用户的了解调整说话方式和语气
- **台词学习** — 通过角色原作台词库检索，让回复更贴合角色
- **多角色隔离** — 每个角色独立记忆，互不干扰

## 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置 API Key（三种方式任选）
export AIBOT_LLM__API_KEY="sk-xxx"
export AIBOT_LLM__PROVIDER="qwen"   # deepseek / moonshot / qwen / openai

# 3. 启动终端测试
python main.py

# 4. 启动 QQ 机器人服务（需配合 go-cqhttp）
python main.py --bot server
```

## 项目结构

```
Echo_Bot/
├── main.py                     # 入口
├── config.py                   # 配置（YAML + 环境变量 + .env）
├── characters/                 # 角色卡 JSON
│   ├── 布偶熊.json
│   ├── 露西亚-誓焰.json
│   ├── 林黛玉.json
│   └── 绫波丽.json
├── core/
│   ├── engine.py               # 对话引擎
│   ├── models.py               # 数据模型
│   ├── character_manager.py    # 角色管理
│   ├── profile_manager.py      # 用户档案（SQLite）
│   ├── prompt_builder.py       # 提示词构建
│   ├── memory_parser.py        # MEMORY 解析
│   ├── context_manager.py      # 对话上下文
│   ├── llm_client.py           # LLM API 客户端
│   └── retriever.py            # 台词检索
├── bot/
│   ├── console_bot.py          # 终端测试
│   └── server_bot.py           # QQ 机器人服务
├── Dockerfile & docker-compose.yml
└── requirements.txt
```

## 支持的 AI 厂商

| provider | 厂商 | 默认模型 |
|---|---|---|
| `qwen` | 阿里通义千问 | qwen-plus |
| `deepseek` | DeepSeek | deepseek-chat |
| `moonshot` | Moonshot/Kimi | moonshot-v1-8k |
| `openai` | OpenAI | gpt-4o-mini |
| `ollama` | 本地部署 | qwen2.5:7b |

## License

MIT
