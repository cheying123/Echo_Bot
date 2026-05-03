"""
MEMORY 块解析器：从 AI 回复中提取 <<MEMORY>> JSON
"""

from __future__ import annotations

import json
import logging
import re
from typing import Optional

from core.models import (
    MemoryBlock,
    MemoryObservation,
    RelationshipState,
    StrategyAdjustment,
)

logger = logging.getLogger(__name__)

# MEMORY 块匹配正则（完整或有内容的）
MEMORY_PATTERN = re.compile(
    r'<<<MEMORY>>>\s*(\{.*?\})?\s*<<<END_MEMORY>>>',
    re.DOTALL | re.IGNORECASE,
)

# 宽松匹配：可能缺少 >>> 或大小写不一致
MEMORY_PATTERN_LAX = re.compile(
    r'<<<?MEMORY>>>?\s*(\{.*?\})?\s*<<<?END_MEMORY>>>?',
    re.DOTALL | re.IGNORECASE,
)


def extract_memory_block(text: str) -> Optional[str]:
    """从回复文本中提取 MEMORY JSON 字符串"""
    # 先严格匹配
    match = MEMORY_PATTERN.search(text)
    if match:
        return match.group(1)

    # 宽松匹配
    match = MEMORY_PATTERN_LAX.search(text)
    if match:
        logger.warning("使用宽松模式匹配到 MEMORY 块")
        return match.group(1)

    return None


def strip_memory_block(text: str) -> str:
    """从回复中移除 MEMORY 块，只保留对话内容"""
    return MEMORY_PATTERN.sub("", text).strip()


def _normalize_str_field(data: dict, field: str, default: str = "") -> str:
    """将字段统一转为字符串（AI 有时会输出列表）"""
    val = data.get(field, default)
    if isinstance(val, list):
        val = "、".join(str(v) for v in val)
    return str(val) if val else default


def parse_memory_json(json_str: str) -> Optional[MemoryBlock]:
    """解析 MEMORY JSON 字符串为 MemoryBlock 对象"""
    # 清理：去除控制字符
    json_str_clean = re.sub(r'[\x00-\x1f\x7f]', '', json_str)

    data = None

    # 尝试标准 JSON 解析
    try:
        data = json.loads(json_str_clean)
    except json.JSONDecodeError:
        # 尝试 json5（更宽容）
        try:
            import json5
            data = json5.loads(json_str_clean)
            logger.debug("使用 json5 成功解析 MEMORY")
        except ImportError:
            pass
        except Exception:
            pass

    if data is None:
        # 尝试修复常见 JSON 问题
        data = _repair_json(json_str_clean)
        if data is None:
            logger.warning("MEMORY JSON 解析失败，内容前100字符: %s", json_str_clean[:100])
            return None

    try:
        # 构建 MemoryBlock
        obs_data = data.get("observations", {}) or {}
        rel_data = data.get("relationship", {}) or {}
        strat_data = data.get("strategy_adjustments", {}) or {}

        block = MemoryBlock(
            user_id=str(data.get("user_id", "")),
            timestamp=str(data.get("timestamp", "")),
            observations=MemoryObservation(
                new_traits=obs_data.get("new_traits", []),
                mood=str(obs_data.get("mood", "neutral")),
                interests_mentioned=obs_data.get("interests_mentioned", []),
                speech_pattern=_normalize_str_field(obs_data, "speech_pattern"),
            ),
            relationship=RelationshipState(
                current_stage=str(rel_data.get("current_stage", "陌生人")),
                stage_reason=str(rel_data.get("stage_reason", "")),
                trust_signal=str(rel_data.get("trust_signal", "维持")),
                trust_reason=str(rel_data.get("trust_reason", "")),
                affection_signal=str(rel_data.get("affection_signal", "维持")),
                affection_reason=str(rel_data.get("affection_reason", "")),
            ),
            strategy_adjustments=StrategyAdjustment(
                next_tone=str(strat_data.get("next_tone", "")),
                topics_to_avoid=strat_data.get("topics_to_avoid", []),
                topics_to_explore=strat_data.get("topics_to_explore", []),
            ),
            raw_json=json_str,
        )
        return block
    except Exception as e:
        logger.warning("MEMORY 结构化失败: %s", e)
        return None


def _repair_json(s: str) -> Optional[dict]:
    """尝试修复常见 JSON 格式问题"""
    import re as _re

    # 移除尾逗号
    s = _re.sub(r',\s*([}\]])', r'\1', s)

    # 移除注释（// 或 # 风格）
    s = _re.sub(r'(?m)^\s*//.*$', '', s)
    s = _re.sub(r'(?m)^\s*#.*$', '', s)

    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass

    # 尝试修复单引号为双引号
    s = _re.sub(r"(?<!\\)'", '"', s)
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass

    return None


def extract_and_parse(text: str) -> tuple[Optional[MemoryBlock], str]:
    """
    从 AI 回复中提取 MEMORY 块并解析。

    Returns:
        (memory_block, clean_text) — clean_text 是去除了 MEMORY 块后的纯对话
    """
    clean = strip_memory_block(text)
    json_str = extract_memory_block(text)
    if not json_str:
        return None, clean

    block = parse_memory_json(json_str)
    return block, clean
