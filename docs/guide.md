# Echo_Bot 使用指南

## 目录

1. [基础概念](#1-基础概念)
2. [角色卡制作](#2-角色卡制作)
3. [对话系统详解](#3-对话系统详解)
4. [记忆与学习机制](#4-记忆与学习机制)
5. [好感度与关系系统](#5-好感度与关系系统)
6. [管理员指南](#6-管理员指南)
7. [故障排查](#7-故障排查)
8. [API 参考](#8-api-参考)

---

## 1. 基础概念

### 三层架构

Echo_Bot 的核心是三层分离设计：

```
角色卡（Layer 1）→ 定义角色的性格、说话方式、知识边界
     ↓
核心引擎（Layer 2）→ 固定的角色扮演规则 + 学习逻辑
     ↓
用户档案（Layer 3）→ SQLite 存储，按用户 × 角色 × 群聊隔离
```

每次对话流程：

```
用户消息 → 台词检索（从角色台词库找相关台词）
        → 构建提示词（角色设定 + 用户画像 + 台词参考）
        → 调用 AI API
        → 解析回复（提取 MEMORY 块）
        → 更新用户档案（异步）
        → 返回回复文本
```

### 数据存储

所有数据存储在 `data/` 目录：

| 文件 | 内容 |
|---|---|
| `data/bot.db` | SQLite 数据库 |
| `data/bot.log` | 运行日志（自动轮转，10MB/份，保留5份） |

---

## 2. 角色卡制作

### 完整字段说明

```json
{
  "name": "角色名（必填）",
  "source": "出处作品",
  "version": "格式版本号",

  "personality": {
    "core_traits": ["性格标签", "多个标签"],
    "speaking_style": "说话风格描述（最重要，决定AI说话味道）",
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

  "source_dialogues": ["角色的原作台词"],

  "sticker_pack": ["表情包图片URL"],

  "greeting_style": "初次见面的态度风格描述",
  "avatar_description": "外貌描述",
  "relationship_with_user_default": "warm/cold/neutral/wary",

  "conflict_triggers": ["触发情绪波动的话题"],
  "soft_spots": ["角色软肋"],

  "forbidden": ["违禁行为"],
  "forbidden_words": ["违禁用词"],

  "dialogue_config": {
    "max_length": 60,
    "allow_action_description": true,
    "max_questions_per_turn": 1
  }
}
```

### 字段优先级

| 重要度 | 字段 | 作用 |
|---|---|---|
| ⭐⭐⭐ | `personality.core_traits` | 性格标签，AI 理解角色的根基 |
| ⭐⭐⭐ | `personality.speaking_style` | 决定了角色说话的味道 |
| ⭐⭐⭐ | `speech_examples` | 对话范例，至少 3 条 |
| ⭐⭐ | `source_dialogues` | 原作台词越多，模仿越像 |
| ⭐⭐ | `knowledge_boundary` | 防止 AI 说出不该知道的事 |
| ⭐ | `forbidden` / `forbidden_words` | 后端安全过滤 |

### 添加方式

**命令行：**
```bash
python add_character.py --template -n "角色名" -s "出处"
```
然后编辑生成的 JSON 文件。

**交互式：**
```bash
python add_character.py
```
按提示填写信息。

**管理面板：**
启动 `python web/dashboard.py`，在浏览器中添加。

---

## 3. 对话系统详解

### 消息拆分

AI 可以在回复中使用 `[pause]` 标记停顿点：

```
AI 输出：
  指挥官，早上好。[pause]*放下手中的数据板* 今天有什么安排吗？
  
发送效果：
  → 指挥官，早上好。
  → （0.6秒后）*放下手中的数据板* 今天有什么安排吗？
```

不加 `[pause]` 就一条消息发完。

### QQ 表情

AI 可以使用 `[face:ID]` 发送 QQ 表情：

| 代码 | 效果 | 场景 |
|---|---|---|
| `[face:107]` | 😊 微笑 | 日常 |
| `[face:109]` | 😲 惊讶 | 意外 |
| `[face:174]` | 🙄 白眼 | 吐槽 |
| `[face:106]` | 😭 哭泣 | 委屈 |
| `[face:14]` | 👍 强 | 鼓励 |

### 主动对话

私聊中，如果超过 2 小时没说话，角色会从台词库挑一句主动问候。不回复则继续安静。

---

## 4. 记忆与学习机制

### 三层记忆

| 层级 | 范围 | 存储方式 |
|---|---|---|
| 短期 | 最近 8 轮对话原文 | 内存 |
| 中期 | 每 10 轮由 AI 生成的摘要 | SQLite |
| 长期 | 性格标签、兴趣、情绪历史 | SQLite |

### 记忆提取

每 3 轮对话提取一次（可配置），提取的内容：

```json
{
  "new_traits": ["喜欢自嘲"],
  "mood": "positive",
  "interests_mentioned": ["编程"],
  "speech_pattern": "简短直接",
  "trust_signal": "提升",
  "affection_signal": "维持",
  "next_tone": "可以更随意"
}
```

提取是**异步**的，不阻塞回复速度。

### 记忆隔离

```
用户A 在私聊中→ private_QQ号 → 角色X → 记忆 A-X
用户A 在群1中  → group_群号1  → 角色X → 记忆 群1-X
用户A 在群2中  → group_群号2  → 角色X → 记忆 群2-X
```

不同群聊即使绑定同一个角色，记忆也是独立的。

---

## 5. 好感度与关系系统

### 好感度等级

| 好感度 | 关系阶段 | AI 说话方式 |
|---|---|---|
| 1-2 | 陌生人 | 礼貌客气，保持距离 |
| 3-4 | 初识 | 温和聊日常 |
| 5-6 | 熟悉 | 随意自然，偶尔开玩笑 |
| 7-8 | 亲密 | 展现真实情绪 |
| 9-10 | 挚友 | 完全信任，无话不谈 |

### 关系晋升条件

| 阶段 | 条件 |
|---|---|
| 陌生人 → 初识 | 对话 ≥ 5 轮 |
| 初识 → 熟悉 | 对话 ≥ 20 轮 + 信任 ≥ 4 |
| 熟悉 → 亲密 | 对话 ≥ 50 轮 + 信任 ≥ 7 + 好感 ≥ 6 |
| 亲密 → 挚友 | 对话 ≥ 100 轮 + 信任 ≥ 9 + 好感 ≥ 9 |

好感下降时关系也会降级。

---

## 6. 管理员指南

### 管理员命令

| 命令 | 说明 |
|---|---|
| `/管理员 list` | 查看所有管理员 |
| `/管理员 add 2994554807` | 添加管理员 |
| `/管理员 remove 123456` | 移除管理员 |
| `/重载` | 不重启容器重新加载角色卡 |
| `/统计` | 查看运行统计（API 调用、对话轮数、平均响应时间） |
| `/添加角色` | 查看添加角色的指引 |
| `/删除角色 露西亚` | 删除指定角色 |

### 日志管理

日志文件自动轮转，10MB 分割，保留最近 5 份。

### 配置修改

```yaml
# config.yml
llm:
  proxy:
    http: http://127.0.0.1:7890  # 代理配置
memory:
  memory_extraction_interval: 3  # 记忆提取间隔（轮数）
```

配置优先级：`代码默认值 < config.yml < 环境变量 < .env`

---

## 7. 故障排查

### 机器人不回复

1. 检查 LLOneBot 是否连接正常
2. 查看服务器日志：`docker logs qq-ai-bot`
3. 检查 API Key 是否有效
4. 群聊中必须 @ 机器人才会回复

### AI 回复不符合角色

1. 检查 `speech_examples` 是否足够（至少 3 条）
2. 检查 `speaking_style` 描写是否详细
3. 添加更多 `source_dialogues` 台词

### 部署后角色丢失

角色绑定存在 SQLite 中，容器重启不会丢失。但如果删除了 `data/bot.db` 文件，需要重新 `/切换`。

### QQ 登录问题

go-cqhttp 遇到滑块验证：

1. 按照提示打开验证 URL
2. 完成滑块验证
3. go-cqhttp 会自动继续登录

---

## 8. API 参考

### 环境变量

| 变量 | 说明 | 示例 |
|---|---|---|
| `AIBOT_LLM__API_KEY` | AI API Key | `sk-xxx` |
| `AIBOT_LLM__PROVIDER` | AI 厂商 | `qwen` / `deepseek` |
| `AIBOT_LLM__MODEL` | 模型名 | `qwen-plus` |
| `AIBOT_LLM__BASE_URL` | API 地址 | `https://api.deepseek.com/v1` |
| `HTTP_PROXY` | HTTP 代理 | `http://127.0.0.1:7890` |

### 启动参数

| 参数 | 说明 |
|---|---|
| `python main.py` | 终端测试模式 |
| `python main.py --bot server` | QQ 机器人服务 |
| `python main.py -c prod.yml` | 指定配置文件 |
| `python web/dashboard.py` | 启动管理面板 |

### 端口

| 端口 | 服务 |
|---|---|
| 8765 | WebSocket（LLOneBot 连接） |
| 8766 | 管理面板（HTTP） |
