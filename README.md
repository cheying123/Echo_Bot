<p align="center">
  <img src="https://img.shields.io/badge/Echo_Bot-v1.0-667eea?style=flat-square">
  <img src="https://img.shields.io/badge/AI-QQ%20Bot-764ba2?style=flat-square">
  <img src="https://img.shields.io/github/license/cheying123/Echo_Bot?style=flat-square">
  <img src="https://img.shields.io/badge/Python-3.10%2B-blue?style=flat-square">
</p>

<p align="center">
  <a href="README_EN.md">English</a> | <b>简体中文</b>
</p>

<h1 align="center">🎭 Echo_Bot</h1>
<p align="center"><b>AI 角色扮演 QQ 机器人 — 会记住你的性格，越聊越懂你</b></p>

<p align="center">
  <a href="#-快速开始">快速开始</a> •
  <a href="#-功能一览">功能</a> •
  <a href="#-命令大全">命令</a> •
  <a href="#-角色系统">角色</a> •
  <a href="#-开发">开发</a> •
  <a href="#-部署">部署</a>
</p>

---

## 📦 项目介绍

Echo_Bot 是一个专注于**角色扮演体验**的 AI 聊天机器人，专为 QQ 设计。

它不只是冷冰冰的问答机器——它能扮演不同的角色，记住你的性格和喜好，根据对你的了解动态调整说话方式。聊得越多，它越懂你。

### 核心理念

> **角色不只是回答问题的外壳，而是有记忆、有成长、能真正和人建立关系的数字存在。**

---

## ✨ 功能一览

| 功能 | 说明 |
|---|---|
| 🎭 **角色扮演** | 任意切换角色，每个角色有独立的性格、说话风格、知识边界 |
| 🧠 **记忆系统** | 记住你的性格标签、兴趣爱好、情绪变化，越聊越懂你 |
| 📖 **台词学习** | RAG 检索角色原作台词，回复更贴合角色 |
| ❤️ **好感度系统** | 好感随对话增长，说话方式从陌生到亲密自然变化 |
| 🔄 **动态适配** | 根据你的情绪和性格调整语气和话题 |
| ☀️ **天气预报** | 每天早上推送天气，时间可自定义 |
| ⏰ **日程提醒** | 用自然语言设置提醒（"明天早上8点开会"） |
| 💬 **主动对话** | 长时间不说话，角色会主动找话题（仅私聊） |
| 🧩 **插件系统** | 第三方开发者可编写插件扩展功能 |
| 🌐 **管理面板** | 浏览器可视化管理角色和设置 |
| 🐳 **Docker 部署** | 一键容器化部署 |

---

## 🚀 快速开始

### 前置条件

- Python 3.10+
- 一个 AI API Key（支持通义千问 / DeepSeek / Moonshot / OpenAI 等）

### 安装

```bash
# 1. 克隆
git clone https://github.com/cheying123/Echo_Bot.git
cd Echo_Bot

# 2. 安装依赖
pip install -r requirements.txt

# 3. 配置 API Key
echo "AIBOT_LLM__API_KEY=sk-your-key" >> .env
echo "AIBOT_LLM__PROVIDER=qwen" >> .env

# 4. 启动终端测试
python main.py

# 5. 或者启动 QQ 服务
python main.py --bot server
```

### 配置文件

```bash
# .env 文件示例
AIBOT_LLM__API_KEY=sk-xxx           # API Key（必填）
AIBOT_LLM__PROVIDER=qwen            # AI 厂商
AIBOT_LLM__MODEL=qwen-plus          # 模型名
HTTP_PROXY=http://127.0.0.1:7890    # 代理（可选）
```

配置优先级：`代码默认值 < config.yml < 环境变量 < .env`

---

## 📋 命令大全

### 🎭 角色

| 命令 | 说明 |
|---|---|
| `/切换 <角色名>` | 切换到指定角色（如 `/切换 露西亚`） |
| `/角色` | 查看所有可用角色 |
| `/状态` | 查看角色对你的情绪、关系阶段、语气建议 |
| `/档案` | 查看详细画像（性格标签、兴趣、好感度） |

### ☀️ 生活

| 命令 | 说明 |
|---|---|
| `/设置城市 <城市>` | 设置所在城市（如 `/设置城市 北京`） |
| `/天气 on/off` | 开关天气预报推送 |
| `/天气 time <小时>` | 设置推送时间（默认 8 点） |
| `/提醒 <时间> <事项>` | 设置提醒（如 `/提醒 明天8点 开会`） |
| `/提醒 on/off` | 开关日程提醒 |
| `/待办` | 查看待办提醒列表 |

**支持的时间格式：** `明天早上8点` `今天下午3点` `5分钟后` `后天` `2026-05-05 08:00`

### 🔧 管理员

| 命令 | 说明 |
|---|---|
| `/管理员 list` | 查看管理员列表 |
| `/管理员 add <QQ号>` | 添加管理员 |
| `/管理员 remove <QQ号>` | 移除管理员 |
| `/重载` | 重新加载角色卡（无需重启） |
| `/统计` | 查看运行统计 |
| `/添加角色` | 查看添加角色指引 |
| `/删除角色 <名>` | 删除角色 |

---

## 🎨 角色系统

### 角色卡结构

角色卡是 JSON 文件，放在 `characters/` 目录下：

```json
{
  "name": "露西亚",
  "source": "战双帕弥什",
  "personality": {
    "core_traits": ["坚定沉稳", "温柔细腻", "认真执着"],
    "speaking_style": "语气坚定而温柔，习惯用『我们』而不是『我』",
    "habits": ["寒冷时会靠近指挥官", "对阿呆蛙没有抵抗力"],
    "emotional_range": "底色是温柔的坚定"
  },
  "knowledge_boundary": {
    "knows": ["灰鸦小队", "帕弥什病毒"],
    "does_not_know": ["过于复杂的机械原理"],
    "worldview": "战双帕弥什世界观"
  },
  "speech_examples": [
    {"user": "你好", "response": "早上好，指挥官。"}
  ],
  "source_dialogues": [
    "角色在原作中的台词"
  ],
  "sticker_pack": ["https://图片URL.png"]
}
```

### 添加角色

```bash
# 方式一：快速生成模板
python add_character.py --template -n "角色名" -s "出处"

# 方式二：交互式问答
python add_character.py

# 方式三：管理面板
python web/dashboard.py  # 浏览器操作
```

编辑完 JSON 后执行 `/重载` 即可生效，无需重启容器。

---

## 🧠 记忆与好感度

### 三层记忆架构

```
短期记忆（8轮对话原文）  →  存内存
    ↓
中期记忆（AI每10轮生成摘要）  →  存 SQLite
    ↓
长期记忆（性格标签、兴趣、情绪）  →  存 SQLite
```

### 好感度等级

| 好感度 | 关系阶段 | AI 说话方式 |
|---|---|---|
| 1-2 | 陌生人 | 礼貌客气，保持距离 |
| 3-4 | 初识 | 温和聊日常 |
| 5-6 | 熟悉 | 随意自然，偶尔开玩笑 |
| 7-8 | 亲密 | 展现真实情绪 |
| 9-10 | 挚友 | 完全信任，无话不谈 |

### 记忆隔离

| 场景 | 绑定键 | 记忆域 |
|---|---|---|
| QQ 好友私聊 | `private_你的QQ号` | 私聊专属 |
| A 群聊 | `group_A群号` | A 群专属 |
| B 群聊 | `group_B群号` | B 群专属 |

不同群聊绑定同一角色，记忆互不干扰。

---

## 🔌 插件开发

在 `plugins/` 目录下创建 `.py` 文件即可：

```python
from core.plugin_manager import Plugin

class MyPlugin(Plugin):
    name = "myplugin"          # 插件名
    version = "1.0"            # 版本
    description = "说明"       # 描述

    async def on_startup(self):
        print("插件已加载")

    async def on_command(self, cmd, args, event, bind_key):
        if cmd == "ping":
            await self.reply(event, "pong!")
            return True  # 返回 True 表示命令已处理

    async def on_message(self, event, reply):
        # 可以修改 AI 回复内容
        return reply

    def get_commands(self):
        return [{"cmd": "ping", "desc": "测试插件"}]
```

重启后自动加载。

---

## 🌐 管理面板

```bash
python web/dashboard.py
# 访问 http://localhost:8766
```

功能：
- 角色管理（查看、添加、编辑、删除）
- 系统状态监控
- 插件列表查看

---

## 🐳 Docker 部署

```bash
# 构建并启动
docker compose up -d --build

# 查看日志
docker compose logs -f

# 重启
docker compose restart

# 停止
docker compose down
```

---

## 📁 项目结构

```
Echo_Bot/
├── main.py                   # 入口
├── config.py                 # 配置管理
├── add_character.py          # 角色添加工具
│
├── characters/               # 角色卡 JSON
│   ├── 露西亚-誓焰.json
│   ├── 布偶熊.json
│   ├── 486.json
│   ├── Nina.json
│   └── ...
│
├── core/                     # 核心引擎
│   ├── engine.py             # 对话引擎
│   ├── models.py             # 数据模型
│   ├── plugin_manager.py     # 插件系统
│   ├── prompt_builder.py     # 提示词构建
│   ├── profile_manager.py    # 用户档案 (SQLite)
│   ├── memory_parser.py      # MEMORY 解析
│   ├── character_manager.py  # 角色管理
│   ├── context_manager.py    # 对话上下文
│   ├── retriever.py          # 台词检索
│   ├── scheduler.py          # 定时任务
│   └── llm_client.py         # LLM API 客户端
│
├── bot/                      # 机器人前端
│   ├── console_bot.py        # 终端模式
│   └── server_bot.py         # QQ 服务
│
├── plugins/                  # 插件目录
├── web/                      # 管理面板
│   └── dashboard.py
├── docs/                     # 文档
│   └── guide.md
│
├── data/                     # 运行时数据
│   ├── bot.db                # SQLite 数据库
│   └── bot.log               # 日志文件
│
├── Dockerfile                # Docker 构建
├── docker-compose.yml        # Docker 编排
└── requirements.txt          # 依赖
```

---

## 🤝 贡献

欢迎提交 Issue 和 Pull Request。

1. Fork 本仓库
2. 创建特性分支 (`git checkout -b feature/amazing`)
3. 提交改动 (`git commit -m "feat: 添加某个功能"`)
4. 推送到分支 (`git push origin feature/amazing`)
5. 提交 Pull Request

---

## 📄 License

MIT
