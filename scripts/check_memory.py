"""
监控脚本：检查 AI 回复中是否包含 MEMORY 块

用法：
  python scripts/check_memory.py         # 检查最近10条对话
  python scripts/check_memory.py --watch # 实时监控
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

_project_root = Path(__file__).parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))


def check_db():
    """检查 SQLite 中对话日志的 MEMORY 字段"""
    from config import load_config
    from core.profile_manager import ProfileManager
    cfg = load_config()
    pm = ProfileManager(cfg.paths["db_path"])

    # 直接从底层 SQLite 查
    import sqlite3
    conn = sqlite3.connect(cfg.paths["db_path"])
    rows = conn.execute(
        "SELECT id, user_id, character_id, memory_json, created_at FROM conversation_logs ORDER BY id DESC LIMIT 20"
    ).fetchall()
    conn.close()

    if not rows:
        print("  数据库中没有任何对话记录")
        return

    print(f"\n  最近 {len(rows)} 条对话记录:")
    print(f"  {'ID':>4} {'用户':>10} {'角色':>12} {'有MEMORY':>10} {'时间':>20}")
    print(f"  {'-'*60}")

    has_memory_count = 0
    for row in rows:
        rid, uid, cid, mem_json, ts = row
        has_memory = bool(mem_json and mem_json != "null" and len(mem_json) > 10)
        if has_memory:
            has_memory_count += 1
        print(f"  {rid:>4} {uid[:10]:>10} {cid[:12]:>12} {'✅' if has_memory else '❌':>10} {ts[:19]:>20}")

    print(f"\n  总结: {has_memory_count}/{len(rows)} 条包含 MEMORY 块")
    print(f"  MEMORY 生成率: {has_memory_count/max(len(rows),1)*100:.0f}%")

    # 检查错误日志
    print(f"\n  建议:")
    if has_memory_count == 0:
        print(f"  · AI 没有输出 MEMORY 块，信任/关系/情绪都不会更新")
        print(f"  · 检查 prompt_builder.py 中的 MEMORY 模板格式")
        print(f"  · 考虑换一个模型或修改提示词")
        print(f"  · 当前已通过 _save_user_traits 兜底更新信任/关系（但依赖对话触发）")
    elif has_memory_count < len(rows) * 0.5:
        print(f"  · AI 偶尔输出 MEMORY 块，但不稳定")
    else:
        print(f"  · AI 正常输出 MEMORY 块")


def test_parse_memory():
    """测试解析器能否正确解析 MEMORY 块"""
    from core.memory_parser import extract_and_parse

    test_cases = [
        "你好呀\n<<<MEMORY>>>{\"user_id\":\"test\",\"observations\":{\"mood\":\"positive\"},\"relationship\":{},\"strategy_adjustments\":{}}<<<END_MEMORY>>>",
        "没有 MEMORY 块的普通回复",
        "空 MEMORY<<<MEMORY>>><<<END_MEMORY>>>",
    ]

    print(f"\n  MEMORY 解析器测试:")
    for tc in test_cases:
        block, clean = extract_and_parse(tc)
        status = "✅" if block else "❌"
        print(f"  {status} \"{tc[:40]}...\" → {'解析成功' if block else '无 MEMORY'}")


if __name__ == "__main__":
    watch = "--watch" in sys.argv or "-w" in sys.argv

    print(f"  Echo_Bot MEMORY 诊断")
    print(f"  {'='*40}")

    test_parse_memory()
    check_db()

    if watch:
        print(f"\n  每 30 秒刷新...\n")
        while True:
            time.sleep(30)
            check_db()
