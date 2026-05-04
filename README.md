# Echo_Bot — AI 角色扮演 QQ 机器人

一个能扮演不同角色、学习用户性格、动态调整说话方式的 QQ 聊天机器人。

> **核心理念**：角色不只是回答问题的外壳，而是有记忆、有成长、能真正和人建立关系的数字存在。

---

## 目录

- [系统架构](#系统架构)
- [核心功能](#核心功能)
- [快速开始](#快速开始)
- [QQ 机器人部署](#qq-机器人部署)
- [角色系统](#角色系统)
- [记忆与学习机制](#记忆与学习机制)
- [配置说明](#配置说明)
- [可用命令](#可用命令)
- [Docker 部署](#docker-部署)
- [项目结构](#项目结构)

---

## 系统架构

Echo_Bot 采用三层分离架构：

```
┌─────────────────────────────────────────────────┐
│  Layer 1: 角色卡 (Character Card)                │
│  纯 JSON 文件，可随时替换，一个角色一个文件          │
│  性格、说话风格、知识边界、台词库                    │
├─────────────────────────────────────────────────┤
│  Layer 2: 核心引擎 (Core Engine)                  │
│  固定提示词框架 + 对话编排 + LLM 调用               │
│  角色扮演协议、动态适配规则、记忆提取逻辑              │
├─────────────────────────────────────────────────┤
│  Layer 3: 用户档案 (User Profile)                 │
│  SQLite 存储，按用户+角色隔离                      │
│  性格标签、情绪历史、关系阶段、对话摘要               │
└─────────────────────────────────────────────────┘
```

### 数据流

```
用户消息 → 构建提示词 → LLM API → 解析回复
    ↑                        ↓
用户档案 ←────────── MEMORY 块解析 → 合并画像
    ↑
台词检索 ← 角色台词库（相似度匹配 Top-5）
```

---

## 核心功能

### 🎭 角色扮演
- 任意切换角色，每个角色有独立的**性格、说话风格、知识边界、世界观**
- 角色卡为纯 JSON 文件，热加载，随时可以增删改

### 🧠 记忆系统
- **短期记忆**：保留最近对话原文（默认 8 轮）
- **中期记忆**：每 10 轮由 AI 生成对话摘要
- **长期记忆**：每轮提取用户特征，累积到画像中
- **记忆隔离**：不同角色的记忆完全独立，互不干扰

### 📖 台词学习（RAG）
- 角色卡可内置原作台词库
- 每次对话前检索与当前话题最相关的台词
- 注入提示词中供 AI 参考，让回复更贴合原作

### 🔄 动态适配
根据对用户的了解，自动调整：

| 维度 | 变化方式 |
|---|---|
| 关系阶段 | 陌生人 → 初识 → 熟悉 → 亲密 → 挚友（对话轮数和好感度决定） |
| 说话语气 | 根据用户情绪和性格特征调整 |
| 话题选择 | 记录用户感兴趣和反感的话题 |
| 情绪回应 | 检测到负面情绪时优先关怀 |

---

## 快速开始

### 前置需求

- Python 3.10+
- 一个 AI API 的 Key（支持 DeepSeek / 通义千问 / Moonshot / OpenAI 等）

### 安装与运行

```bash
# 1. 克隆项目
git clone https://github.com/cheying123/Echo_Bot.git
cd Echo_Bot

# 2. 安装依赖
pip install -r requirements.txt

# 3. 配置 API Key
echo "AIBOT_LLM__API_KEY=sk-your-key" >> .env
echo "AIBOT_LLM__PROVIDER=qwen" >> .env      # 可选：deepseek / moonshot / qwen / openai

# 4. 启动终端测试模式
python main.py
```

启动后选一个角色，直接开始对话：

```
可用角色：
  1. 布偶熊 [战双帕弥什] — 傲娇、腹黑、吐槽役
  2. 露西亚 [战双帕弥什] — 坚定沉稳、温柔细腻
  3. 林黛玉 [红楼梦] — 聪慧敏感、多愁善感
  4. 绫波丽 [新世纪福音战士] — 三无少女、冷静

输入角色编号或名称:
```

---

## QQ 机器人部署

### 方案一：LLOneBot（推荐，Windows 用）

1. 下载安装 [QQ NT 版](https://im.qq.com/)
2. 下载 [LLOneBot](https://github.com/LLOneBot/LLOneBot/releases/latest)
3. 解压到 QQ 插件目录 `C:\Users\用户名\AppData\Local\QQNT\plugins\`
4. 启动 QQ，登录机器人小号
5. 在 LLOneBot 设置中添加反向 WebSocket：`ws://你的服务器IP:8765`

### 方案二：go-cqhttp（Linux 用）

```yaml
# go-cqhttp config.yml
account:
  uin: 你的QQ号
  password: '你的密码'
servers:
  - ws-reverse:
      universal: ws://127.0.0.1:8765
```

### 服务器端启动

```bash
# 终端测试
python main.py

# QQ 机器人服务
python main.py --bot server
```

---

## 角色系统

### 角色卡结构

角色卡是 JSON 文件，放在 `characters/` 目录下，重启后自动加载。

```json
{
  "name": "角色名",
  "source": "出处作品",
  "personality": {
    "core_traits": ["标签1", "标签2"],
    "speaking_style": "说话风格描述（最重要）",
    "habits": ["习惯动作"],
    "emotional_range": "情绪表达范围"
  },
  "knowledge_boundary": {
    "knows": ["角色应该知道的事物"],
    "does_not_know": ["角色不应该知道的事物"],
    "worldview": "角色所处的世界观"
  },
  "speech_examples": [
    {"user": "用户说的话", "response": "角色的回应"}
  ],
  "source_dialogues": [
    "角色在原作中的台词1",
    "角色在原作中的台词2"
  ],
  "greeting_style": "初次接触时的态度风格描述",
  "avatar_description": "外貌描述",
  "relationship_with_user_default": "warm",
  "conflict_triggers": ["触发情绪波动的话题"],
  "soft_spots": ["角色软肋"],
  "forbidden": ["角色不能做的事"],
  "dialogue_config": {
    "max_length": 60,
    "allow_action_description": true
  }
}
```

### 添加新角色

1. 在 `characters/` 目录下新建 `.json` 文件
2. 至少填写 `name`、`personality.core_traits`、`personality.speaking_style`、`speech_examples`
3. 重启程序即可在角色列表中看到
4. 台词越多，AI 模仿越像

---

## 记忆与学习机制

### 学习流程

```
每轮对话后，AI 输出 MEMORY 块：
{
  "observations": {
    "new_traits": ["喜欢自嘲"],
    "mood": "positive",
    "interests_mentioned": ["编程"],
    "speech_pattern": "简短直接"
  },
  "relationship": {
    "trust_signal": "提升",
    "affection_signal": "维持"
  },
  "strategy_adjustments": {
    "next_tone": "可以更随意",
    "topics_to_explore": ["游戏"]
  }
}
```

- 特征标签累积去重
- 情绪记录最近 30 条用于趋势分析
- 关系阶段由后端按规则晋升（不依赖 AI 判断）
- 记忆提取间隔可配置，默认每 3 轮一次

### 记忆隔离

```
用户A（QQ号 111）
├── 角色X
│   ├── 关系阶段: 熟悉
│   ├── 兴趣: ["编程", "动漫"]
│   └── 对话摘要: ...
├── 角色Y
│   ├── 关系阶段: 陌生人
│   └── 对话摘要: ...
用户B（QQ号 222）
└── 角色X
    ├── 关系阶段: 初识
    └── ...
```

---

## 配置说明

### 优先级

```
代码默认值 < config.yml < 环境变量 < .env 文件
```

### 核心配置项

| 配置 | 环境变量 | 说明 |
|---|---|---|
| AI 供应商 | `AIBOT_LLM__PROVIDER` | qwen / deepseek / moonshot / openai |
| API Key | `AIBOT_LLM__API_KEY` | 建议用 .env 设置 |
| 模型名 | `AIBOT_LLM__MODEL` | 不填则用厂商预设 |
| API 地址 | `AIBOT_LLM__BASE_URL` | 不填则用厂商预设 |
| 代理 | `HTTP_PROXY` | 访问外网 API 时使用 |

### 支持的 AI 厂商

| provider | 厂商 | 默认模型 | 国内直连 |
|---|---|---|---|
| `qwen` | 阿里通义千问 | qwen-plus | ✅ |
| `deepseek` | DeepSeek | deepseek-chat | ✅ |
| `moonshot` | Moonshot/Kimi | moonshot-v1-8k | ✅ |
| `hunyuan` | 腾讯混元 | hunyuan-standard | ✅ |
| `openai` | OpenAI | gpt-4o-mini | ❌ 需代理 |
| `ollama` | 本地部署 | qwen2.5:7b | ✅ |

---

## 可用命令

| 命令 | 说明 |
|---|---|
| `/switch <角色名>` | 切换当前对话角色 |
| `/roles` | 查看所有可用角色 |
| `/status` | 查看角色对你的情绪、关系阶段、语气建议 |
| `/profile` | 查看详细用户画像（性格标签、兴趣、好感度等） |
| `/help` | 显示帮助 |

私聊直接发送命令即可。群聊需要 @机器人后发送命令。

---

## Docker 部署

### 构建并运行

```bash
docker compose up -d --build
```

### 环境变量配置

```bash
cp .env.example .env
# 编辑 .env 填入 API Key
```

### 生产部署建议

- 数据库文件保存在 `./data` 目录下（已挂载卷）
- 日志文件自动轮转，10MB 分割，保留 5 份
- 健康检查每 30 秒一次

---

## 项目结构

```
Echo_Bot/
├── main.py                        # 程序入口
├── config.py                      # 配置管理
├── config.yml                     # 默认配置文件
├── requirements.txt               # Python 依赖
├── .env.example                   # 环境变量模板
├── Dockerfile                     # Docker 构建
├── docker-compose.yml             # Docker 编排
│
├── characters/                    # 角色卡目录
│   ├── 布偶熊.json                  # 战双帕弥什
│   ├── 露西亚-誓焰.json              # 战双帕弥什
│   ├── 林黛玉.json                  # 红楼梦
│   └── 绫波丽.json                  # EVA
│
├── core/                          # 核心引擎
│   ├── engine.py                  # 对话编排主逻辑
│   ├── models.py                  # 数据模型（Pydantic）
│   ├── character_manager.py       # 角色卡管理
│   ├── profile_manager.py         # 用户档案（SQLite）
│   ├── prompt_builder.py          # 提示词构建
│   ├── memory_parser.py           # MEMORY 解析
│   ├── context_manager.py         # 短期对话上下文
│   ├── llm_client.py              # LLM API 客户端
│   └── retriever.py               # 台词检索
│
├── bot/                           # 机器人前端
│   ├── console_bot.py             # 终端交互模式
│   └── server_bot.py              # QQ 机器人服务
│
└── data/                          # 运行时数据
    ├── bot.db                     # 用户画像数据库
    └── bot.log                    # 运行日志
```

---

## License

MIT
