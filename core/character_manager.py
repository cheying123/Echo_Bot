"""
角色卡管理器：加载、校验、列出角色
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional

from core.models import CharacterCard

logger = logging.getLogger(__name__)


class CharacterManager:
    """角色卡管理器"""

    def __init__(self, characters_dir: str):
        self._dir = Path(characters_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._cache: Dict[str, CharacterCard] = {}
        self._load_all()

    # ---- 公开方法 ----

    def list_characters(self) -> List[dict]:
        """列出所有可用角色（简要信息）"""
        return [
            {
                "id": cid,
                "name": card.name,
                "source": card.source,
                "traits": card.personality.core_traits[:3],
            }
            for cid, card in self._cache.items()
        ]

    def get_character(self, character_id: str) -> Optional[CharacterCard]:
        """按 ID 获取角色"""
        return self._cache.get(character_id)

    def get_character_names(self) -> List[str]:
        return [c.name for c in self._cache.values()]

    def get_character_id_by_name(self, name: str) -> Optional[str]:
        for cid, card in self._cache.items():
            if card.name == name:
                return cid
        return None

    def reload(self):
        """重新加载所有角色卡"""
        self._cache.clear()
        self._load_all()

    def add_character(self, card: CharacterCard) -> str:
        """添加新角色并保存到文件"""
        character_id = self._to_id(card.name)
        file_path = self._dir / f"{character_id}.json"

        if file_path.exists():
            raise FileExistsError(f"角色卡已存在: {file_path}")

        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(card.model_dump(mode="json", exclude_none=True), f, ensure_ascii=False, indent=2)

        self._cache[character_id] = card
        logger.info(f"新增角色: {card.name} ({character_id})")
        return character_id

    # ---- 内部方法 ----

    def _load_all(self):
        """扫描目录加载所有 JSON 角色卡"""
        if not self._dir.exists():
            logger.warning(f"角色目录不存在: {self._dir}")
            return

        for json_file in sorted(self._dir.glob("*.json")):
            try:
                card = self._load_single(json_file)
                character_id = self._to_id(card.name)
                self._cache[character_id] = card
                logger.info(f"加载角色: {card.name} ({character_id}) <- {json_file.name}")
            except Exception as e:
                logger.error(f"加载角色卡失败 {json_file.name}: {e}")

    def _load_single(self, path: Path) -> CharacterCard:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        card = CharacterCard(**data)

        # 校验并警告
        missing = card.validate_card()
        if missing:
            logger.warning(f"角色卡 {path.name} 缺少推荐字段: {missing}")

        return card

    @staticmethod
    def _to_id(name: str) -> str:
        """中文名转拉丁字母 ID（拼音首字母降级为简单 hash）"""
        import hashlib
        # 尝试用 ascii 可打印字符
        safe = "".join(c for c in name if c.isascii() and c.isalnum()).lower()
        if safe:
            return safe
        # 纯中文名，用 hash 前缀
        h = hashlib.md5(name.encode()).hexdigest()[:8]
        return f"char_{h}"
