# Echo_Bot

AI 角色扮演聊天机器人，专为 QQ 设计。可扮演不同角色、学习用户性格、动态调整说话方式。

[![GitHub](https://img.shields.io/badge/GitHub-Echo_Bot-blue)](https://github.com/cheying123/Echo_Bot)

---

## 快速导航

- [快速开始](#快速开始)
- [命令大全](#命令大全)
- [角色系统](#角色系统)
- [记忆与好感度](#记忆与好感度)
- [QQ 部署](#qq-部署)
- [插件开发](#插件开发)
- [管理面板](#管理面板)
- [Docker 部署](#docker-部署)
- [系统架构](#系统架构)

---

## 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置 API Key
echo "AIBOT_LLM__API_KEY=sk-your-key" >> .env
echo "AIBOT_LLM__PROVIDER=qwen" >> .env

# 3. 启动终端测试
python main.py

# 4. 或者启动 QQ 机器人服务
python main.py --bot server
```

支持的 AI 厂商一键切换（改 `.env` 的 `AIBOT_LLM__PROVIDER`）：

| provider | 厂商 | 默认模型 | 国内直连 |
|---|---|---|---|
| `qwen` | 阿里通义千问 | qwen-plus | ✅ |
| `deepseek` | DeepSeek | deepseek-chat | ✅ |
| `moonshot` | Moonshot/Kimi | moonshot-v1-8k | ✅ |
| `openai` | OpenAI | gpt-4o-mini | ❌ 需代理 |
| `ollama` | 本地部署 | qwen2.5:7b | ✅ |

---

## 命令大全

### 🎭 角色

| 命令 | 说明 |
|---|---|
| `/切换 <角色名>` | 切换到指定角色 |
| `/角色` | 查看所有可用角色 |
| `/状态` | 查看角色对你的情绪、关系阶段、语气建议 |
| `/档案` | 查看详细画像（性格标签、兴趣、好感度） |

### ☀️ 生活

| 命令 | 说明 |
|---|---|
| `/设置城市 <城市>` | 设置所在城市，每日推送天气预报 |
| `/天气 on/off` | 开关天气预报推送 |
| `/天气 time <小时>` | 设置天气预报推送时间（默认 8 点） |
| `/提醒 <时间> <事项>` | 设置日程提醒 |
| `/提醒 on/off` | 开关日程提醒 |
| `/待办` | 查看待办提醒列表 |

时间格式：`明天早上8点` `今天下午3点` `5分钟后` `后天`

### 🔧 管理员

| 命令 | 说明 |
|---|---|
| `/管理员 list` | 查看管理员列表 |
| `/管理员 add <QQ号>` | 添加管理员 |
| `/管理员 remove <QQ号>` | 移除管理员 |
| `/重载` | 重新加载角色卡（无需重启容器） |
| `/统计` | 查看运行统计数据 |
| `/添加角色` | 查看添加角色指引 |
| `/删除角色 <名>` | 删除指定角色 |

---

## 角色系统

角色卡是 JSON 文件，放在 `characters/` 目录下：

```json
{
  "name": "露西亚",
  "source": "战双帕弥什",
  "personality": {
    "core_traits": ["坚定沉稳", "温柔细腻"],
    "speaking_style": "语气坚定而温柔..."
  },
  "speech_examples": [
    {"user": "你好", "response": "（角色的回应）"}
  ],
  "source_dialogues": [
    "角色在原作中的台词..."
  ],
  "sticker_pack": [
    "https://图片URL.png"
  ]
}
```

**添加角色：**
```bash
python add_character.py --template -n "角色名" -s "出处"
```
或通过管理面板网页添加。

---

## 记忆与好感度

| 机制 | 说明 |
|---|---|
| 短期记忆 | 保留最近若干轮对话原文 |
| 长期记忆 | 性格标签、兴趣、情绪历史累积 |
| 好感度 | 1-10，随对话增加，说话语气随之变化 |
| 关系阶段 | 陌生人 → 初识 → 熟悉 → 亲密 → 挚友 |
| 记忆隔离 | 不同角色 × 不同群聊的记忆互不干扰 |
| 主动对话 | 长时间不说话，角色会主动找话题（仅私聊） |

---

## QQ 部署

### 方案一：LLOneBot（Windows 推荐）

1. 安装 [QQ NT 版](https://im.qq.com/)
2. 下载 [LLOneBot](https://github.com/LLOneBot/LLOneBot/releases)
3. 解压到 `C:\Users\用户名\AppData\Local\QQNT\plugins\`
4. 重启 QQ，进入 LLOneBot 设置
5. 添加反向 WebSocket：`ws://你的服务器IP:8765`
6. 在 QQ 中发送 `/帮助` 开始使用

### 方案二：go-cqhttp（Linux）

```yaml
# go-cqhttp config.yml
account:
  uin: 你的QQ号
  password: '密码'
servers:
  - ws-reverse:
      universal: ws://127.0.0.1:8765
```

---

## 插件开发

在 `plugins/` 目录下创建 `.py` 文件：

```python
from core.plugin_manager import Plugin

class MyPlugin(Plugin):
    name = "myplugin"
    version = "1.0"
    description = "我的第一个插件"

    async def on_startup(self):
        print("插件已加载")

    async def on_command(self, cmd, args, event, bind_key):
        if cmd == "ping":
            await self.reply(event, "pong!")
            return True  # 返回 True 表示命令已处理

    async def on_message(self, event, reply):
        # 可修改回复内容
        return reply

    def get_commands(self):
        # 插件的命令会出现在 /帮助 中
        return [{"cmd": "ping", "desc": "测试插件是否工作"}]
```

重启后自动加载。

---

## 管理面板

```bash
# 启动 Web 管理界面
python web/dashboard.py

# 浏览器访问
# http://localhost:8766
```

功能：
- 可视化管理角色（添加、编辑、删除）
- 查看系统状态（API 调用次数、角色数量）
- 查看插件列表

---

## Docker 部署

```bash
# 构建并启动
docker compose up -d --build

# 查看日志
docker compose logs -f

# 重启
docker compose restart
```

---

## 系统架构

```
Echo_Bot/
├── main.py                  # 程序入口
├── config.py                # 配置管理
├── add_character.py         # 角色添加工具
├── characters/              # 角色卡 JSON
├── plugins/                 # 插件目录
│   └── __init__.py
├── web/                     # 管理面板
│   └── dashboard.py
├── core/                    # 核心引擎
│   ├── engine.py            # 对话引擎
│   ├── models.py            # 数据模型
│   ├── plugin_manager.py    # 插件系统
│   ├── prompt_builder.py    # 提示词构建
│   ├── profile_manager.py   # 用户档案(SQLite)
│   ├── memory_parser.py     # MEMORY 解析
│   ├── character_manager.py # 角色管理
│   ├── context_manager.py   # 对话上下文
│   ├── retriever.py         # 台词检索
│   ├── scheduler.py         # 定时任务
│   └── llm_client.py        # LLM API 客户端
├── bot/                     # 机器人前端
│   ├── console_bot.py       # 终端模式
│   └── server_bot.py        # QQ 服务
└── data/                    # 运行时数据
    ├── bot.db               # 用户画像
    └── bot.log              # 运行日志
```
