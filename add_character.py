"""
角色添加工具 — 交互式生成角色卡 JSON

用法：
  python add_character.py
  python add_character.py --name "露西亚" --source "战双帕弥什"  # 跳过问答，生成模板
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

CHARACTERS_DIR = Path(__file__).parent / "characters"
CHARACTERS_DIR.mkdir(exist_ok=True)


def prompt(text: str, default: str = "") -> str:
    """带默认值的输入"""
    if default:
        hint = f"（默认: {default}）"
    else:
        hint = ""
    val = input(f"  {text}{hint}: ").strip()
    return val if val else default


def prompt_list(text: str) -> list[str]:
    """输入逗号分隔的列表"""
    val = input(f"  {text}（逗号分隔）: ").strip()
    return [v.strip() for v in val.split("，") if v.strip()] if val else []


def prompt_lines(text: str) -> str:
    """多行输入（空行结束）"""
    print(f"  {text}（输入空行结束）: ")
    lines = []
    while True:
        line = input("    ").strip()
        if not line:
            break
        lines.append(line)
    return "\n".join(lines)


def make_character(name: str, source: str) -> dict:
    """生成角色卡"""
    print(f"\n正在创建角色「{name}」")
    print("（直接回车使用默认值，后续可以手动编辑 JSON 调整）\n")

    traits = prompt_list("性格标签（如: 傲娇、毒舌、技术宅）")
    if not traits:
        traits = ["待补充"]

    style = prompt("说话风格描述（最重要，决定说话味道）")
    if not style:
        style = "待补充"

    worldview = prompt("世界观（角色生活在什么样的世界）")
    greeting = prompt("初识态度（初次见面给人的感觉）", "neutral")
    avatar = prompt("外貌描述")
    max_len = prompt("回复最大字数", "60")

    print("\n--- 对话示例（至少 3 条，角色说话的灵魂） ---")
    examples = []
    example_count = 0
    while example_count < 3:
        print(f"\n  示例 {example_count + 1}:")
        user_line = input("    用户说: ").strip()
        if not user_line:
            if example_count == 0:
                print("    （至少需要一条示例）")
                continue
            break
        bot_line = input("    角色回: ").strip()
        if not bot_line:
            print("    （示例需要角色回应）")
            continue
        examples.append({"user": user_line, "response": bot_line})
        example_count_count = example_count + 1  # 这只是为了计数
        example_count += 1
        if example_count >= 3:
            more = input("\n  继续添加示例？(y/n): ").strip().lower()
            if more != "y":
                break

    print("\n--- 台词库（可选，让角色更像原作） ---")
    print("  输入角色的经典台词，一句一行，空行结束")
    dialogues = prompt_lines("台词")

    card = {
        "name": name,
        "source": source,
        "version": "1.0",
        "personality": {
            "core_traits": traits,
            "speaking_style": style,
            "habits": [],
            "emotional_range": "",
        },
        "knowledge_boundary": {
            "knows": [],
            "does_not_know": [],
            "worldview": worldview or f"《{source}》的世界",
        },
        "speech_examples": examples,
        "source_dialogues": dialogues,
        "greeting_style": greeting,
        "avatar_description": avatar,
        "relationship_with_user_default": "neutral",
        "development_arc": "",
        "conflict_triggers": [],
        "soft_spots": [],
        "forbidden": [
            "不能以 AI 或机器人的身份说话",
            "不能跳出角色身份",
        ],
        "forbidden_words": [],
        "dialogue_config": {
            "max_length": int(max_len) if max_len.isdigit() else 60,
            "allow_action_description": True,
            "max_questions_per_turn": 1,
        },
    }

    return card


def save_character(card: dict) -> Path:
    """保存角色卡到文件"""
    # 文件名取前 4 个字
    short = card["name"][:4]
    filepath = CHARACTERS_DIR / f"{short}.json"

    if filepath.exists():
        old_name = json.load(open(filepath, "r", encoding="utf-8")).get("name", "")
        print(f"\n  文件 {filepath.name} 已存在（当前角色: {old_name}）")
        overwrite = input("  覆盖？(y/n): ").strip().lower()
        if overwrite != "y":
            # 加序号
            i = 2
            while filepath.exists():
                filepath = CHARACTERS_DIR / f"{short}_{i}.json"
                i += 1
            print(f"  另存为: {filepath.name}")

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(card, f, ensure_ascii=False, indent=2)

    print(f"\n[OK] 角色卡已保存: {filepath}")
    return filepath


def make_template(name: str, source: str) -> dict:
    """快速生成模板（返回卡片 dict）"""
    return {
        "name": name,
        "source": source,
        "version": "1.0",
        "personality": {
            "core_traits": ["待补充"],
            "speaking_style": "待补充",
            "habits": [],
            "emotional_range": "",
        },
        "knowledge_boundary": {
            "knows": [],
            "does_not_know": [],
            "worldview": f"《{source}》的世界" if source else "",
        },
        "speech_examples": [
            {"user": "你好", "response": "（角色的回应）"},
            {"user": "今天天气真好", "response": "（角色的回应）"},
            {"user": "在吗？", "response": "（角色的回应）"},
        ],
        "source_dialogues": [],
        "greeting_style": "",
        "avatar_description": "",
        "relationship_with_user_default": "neutral",
        "development_arc": "",
        "conflict_triggers": [],
        "soft_spots": [],
        "forbidden": ["不能以 AI 或机器人的身份说话", "不能跳出角色身份"],
        "forbidden_words": [],
        "dialogue_config": {
            "max_length": 60,
            "allow_action_description": True,
            "max_questions_per_turn": 1,
        },
    }


def main():
    parser = argparse.ArgumentParser(description="Echo_Bot 角色添加工具")
    parser.add_argument("--name", "-n", help="角色名")
    parser.add_argument("--source", "-s", help="出处作品")
    parser.add_argument("--template", "-t", action="store_true", help="快速生成模板（跳过问答）")
    args = parser.parse_args()

    print("=" * 45)
    print("  Echo_Bot — 添加新角色")
    print("=" * 45)

    name = args.name or input("\n角色名: ").strip()
    if not name:
        print("角色名不能为空")
        return

    source = args.source or input("出处作品: ").strip()

    if args.template:
        card = make_template(name, source)
    else:
        card = make_character(name, source)

    filepath = save_character(card)

    print(f"\n现在可以重启机器人来加载「{name}」了。")
    print(f"手动编辑: {filepath}")


if __name__ == "__main__":
    main()
