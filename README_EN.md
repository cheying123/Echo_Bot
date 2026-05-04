<p align="center">
  <img src="https://img.shields.io/badge/Echo_Bot-v1.0-667eea?style=flat-square">
  <img src="https://img.shields.io/badge/AI-QQ%20Bot-764ba2?style=flat-square">
  <img src="https://img.shields.io/github/license/cheying123/Echo_Bot?style=flat-square">
  <img src="https://img.shields.io/badge/Python-3.10%2B-blue?style=flat-square">
</p>

<p align="center">
  <b>English</b> | <a href="README.md">简体中文</a>
</p>

<h1 align="center">🎭 Echo_Bot</h1>
<p align="center"><b>AI Character Role-Playing QQ Bot — Remembers your personality, understands you better over time</b></p>

<p align="center">
  <a href="#-quick-start">Quick Start</a> •
  <a href="#-features">Features</a> •
  <a href="#-commands">Commands</a> •
  <a href="#-character-system">Characters</a> •
  <a href="#-development">Development</a> •
  <a href="#-deployment">Deployment</a>
</p>

---

## 📦 Introduction

Echo_Bot is an AI chatbot focused on **character role-playing**, designed for QQ.

It's not just a Q&A machine — it can扮演 different characters, remember your personality and preferences, and dynamically adjust its speaking style based on how well it knows you. The more you talk, the better it understands you.

### Core Philosophy

> **A character is not just a shell for answering questions — it's a digital being with memories, growth, and the ability to truly connect with people.**

---

## ✨ Features

| Feature | Description |
|---|---|
| 🎭 **Character RP** | Switch between characters, each with unique personality, style, and knowledge |
| 🧠 **Memory System** | Remembers your traits, interests, and mood changes over time |
| 📖 **Source Dialogues** | RAG-based retrieval from character source material for authentic replies |
| ❤️ **Affinity System** | Relationship grows from stranger to best friend as you talk more |
| 🔄 **Dynamic Adaptation** | Adjusts tone and topics based on your mood and personality |
| ☀️ **Weather Forecast** | Daily weather push at customizable time |
| ⏰ **Reminders** | Natural language reminders ("remind me to meet at 8am tomorrow") |
| 💬 **Proactive Chat** | Characters initiate conversation when idle (private chat only) |
| 🧩 **Plugin System** | Third-party developers can extend functionality via plugins |
| 🌐 **Web Dashboard** | Browser-based character and settings management |
| 🐳 **Docker Support** | One-click container deployment |

---

## 🚀 Quick Start

### Prerequisites

- Python 3.10+
- An AI API Key (Qwen / DeepSeek / Moonshot / OpenAI etc.)

### Installation

```bash
# 1. Clone
git clone https://github.com/cheying123/Echo_Bot.git
cd Echo_Bot

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure API Key
echo "AIBOT_LLM__API_KEY=sk-your-key" >> .env
echo "AIBOT_LLM__PROVIDER=qwen" >> .env

# 4. Start console test mode
python main.py

# 5. Or start QQ server mode
python main.py --bot server
```

### Configuration

```bash
# .env example
AIBOT_LLM__API_KEY=sk-xxx           # API Key (required)
AIBOT_LLM__PROVIDER=qwen            # AI provider
AIBOT_LLM__MODEL=qwen-plus          # Model name
HTTP_PROXY=http://127.0.0.1:7890    # Proxy (optional)
```

Config priority: `defaults < config.yml < env vars < .env`

### Supported AI Providers

| Provider | Name | Default Model | Direct Access in China |
|---|---|---|---|
| `qwen` | Alibaba Cloud | qwen-plus | ✅ |
| `deepseek` | DeepSeek | deepseek-chat | ✅ |
| `moonshot` | Moonshot/Kimi | moonshot-v1-8k | ✅ |
| `openai` | OpenAI | gpt-4o-mini | ❌ Proxy needed |
| `ollama` | Local | qwen2.5:7b | ✅ |

---

## 📋 Commands

### 🎭 Character

| Command | Description |
|---|---|
| `/切换 <name>` | Switch to character (e.g. `/切换 露西亚`) |
| `/角色` | List all available characters |
| `/状态` | View emotion, relationship stage, tone suggestion |
| `/档案` | View detailed profile (traits, interests, affinity) |

### ☀️ Life

| Command | Description |
|---|---|
| `/设置城市 <city>` | Set your city for weather (e.g. `/设置城市 北京`) |
| `/天气 on/off` | Toggle weather forecast |
| `/天气 time <hour>` | Set weather push time (default 8) |
| `/提醒 <time> <event>` | Set reminder (e.g. `/提醒 明天8点 开会`) |
| `/提醒 on/off` | Toggle reminders |
| `/待办` | List pending reminders |

**Time formats:** `明天早上8点` `今天下午3点` `5分钟后` `2026-05-05 08:00`

### 🔧 Admin

| Command | Description |
|---|---|
| `/管理员 list` | List admins |
| `/管理员 add <QQ>` | Add admin |
| `/管理员 remove <QQ>` | Remove admin |
| `/重载` | Reload character cards (no restart needed) |
| `/统计` | View statistics |
| `/添加角色` | Guide to add characters |
| `/删除角色 <name>` | Remove a character |

---

## 🎨 Character System

### Character Card Structure

Characters are defined as JSON files in the `characters/` directory:

```json
{
  "name": "Lucia",
  "source": "Punishing: Gray Raven",
  "personality": {
    "core_traits": ["steadfast", "gentle", "dutiful"],
    "speaking_style": "firm yet gentle tone",
    "habits": ["leans closer when speaking", "loves frog plushies"],
    "emotional_range": "calm determination as base"
  },
  "knowledge_boundary": {
    "knows": ["Gray Raven squad", "Punishing virus"],
    "does_not_know": ["modern pop culture"],
    "worldview": "Punishing: Gray Raven universe"
  },
  "speech_examples": [
    {"user": "Hello", "response": "Good morning, Commander."}
  ],
  "source_dialogues": [
    "Character's original lines from the source material"
  ],
  "sticker_pack": ["https://image.url/sticker.png"]
}
```

### Adding Characters

```bash
# Method 1: Quick template
python add_character.py --template -n "Name" -s "Source"

# Method 2: Interactive mode
python add_character.py

# Method 3: Web dashboard
python web/dashboard.py
```

After editing the JSON, run `/重载` to apply changes without restarting.

---

## 🧠 Memory & Affinity

### Three-Tier Memory

```
Short-term (last 8 rounds)  →  RAM
    ↓
Mid-term (summary every 10 rounds)  →  SQLite
    ↓
Long-term (traits, interests, emotions)  →  SQLite
```

### Affinity Levels

| Affinity | Stage | AI Speaking Style |
|---|---|---|
| 1-2 | Stranger | Polite, distant |
| 3-4 | Acquainted | Friendly small talk |
| 5-6 | Familiar | Casual, occasional jokes |
| 7-8 | Close | Shows real emotions |
| 9-10 | Best Friend | Complete trust, fully relaxed |

### Memory Isolation

| Scene | Binding Key | Memory Domain |
|---|---|---|
| Private chat | `private_your_QQ` | Exclusive to private chat |
| Group A | `group_A_id` | Exclusive to Group A |
| Group B | `group_B_id` | Exclusive to Group B |

Same character in different groups = independent memories.

---

## 🔌 Plugin Development

Create a `.py` file in the `plugins/` directory:

```python
from core.plugin_manager import Plugin

class MyPlugin(Plugin):
    name = "myplugin"
    version = "1.0"
    description = "My first plugin"

    async def on_startup(self):
        print("Plugin loaded!")

    async def on_command(self, cmd, args, event, bind_key):
        if cmd == "ping":
            await self.reply(event, "pong!")
            return True

    async def on_message(self, event, reply):
        return reply  # Modify reply if needed

    def get_commands(self):
        return [{"cmd": "ping", "desc": "Test plugin"}]
```

Auto-loaded on next restart.

---

## 🌐 Web Dashboard

```bash
python web/dashboard.py
# Visit http://localhost:8766
```

Features:
- Character management (view, add, edit, delete)
- System status monitoring
- Plugin list

---

## 🐳 Docker Deployment

```bash
# Build and start
docker compose up -d --build

# View logs
docker compose logs -f

# Restart
docker compose restart

# Stop
docker compose down
```

---

## 🤝 Contributing

Issues and Pull Requests are welcome.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing`)
3. Commit your changes (`git commit -m "feat: add amazing feature"`)
4. Push to the branch (`git push origin feature/amazing`)
5. Open a Pull Request

---

## 📄 License

MIT
