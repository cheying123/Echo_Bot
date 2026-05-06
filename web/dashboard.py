"""
Echo_Bot 管理面板

用法：python web/dashboard.py
访问：http://localhost:8766
"""

from __future__ import annotations

import json
import logging
import os
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Any

_project_root = Path(__file__).parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

HTML_PATH = _project_root / "web" / "dashboard.html"
logger = logging.getLogger(__name__)


class DashboardHandler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send_json(self, data: Any, status: int = 200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode())

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length))

    def _load_character_list(self) -> list[dict]:
        char_dir = _project_root / "characters"
        if not char_dir.exists():
            return []
        chars = []
        for f in sorted(char_dir.glob("*.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                chars.append({
                    "id": f.stem, "name": data.get("name", f.stem),
                    "source": data.get("source", ""),
                    "traits": data.get("personality", {}).get("core_traits", []),
                    "personality": data.get("personality", {}),
                    "knowledge_boundary": data.get("knowledge_boundary", {}),
                })
            except Exception as e:
                chars.append({"id": f.stem, "name": f.stem, "error": str(e)})
        return chars

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            html = HTML_PATH.read_text(encoding="utf-8")
            self.wfile.write(html.encode())
        elif self.path in ("/api/chars", "/api/characters"):
            self._send_json({"chars": self._load_character_list()})
        elif self.path == "/api/system":
            self._send_json({
                "version": "1.0.0",
                "python": sys.version.split()[0],
                "characters_dir": str(_project_root / "characters"),
                "data_dir": str(_project_root / "data"),
            })
        elif self.path == "/api/plugins":
            self._send_json([])
        elif self.path == "/api/status":
            try:
                from config import get_config
                cfg = get_config()
                self._send_json({
                    "online": True, "char_count": len(self._load_character_list()),
                    "api_calls": 0, "provider": cfg.llm.get("provider", ""),
                    "model": cfg.llm.get("model", ""),
                })
            except Exception:
                self._send_json({"online": False, "char_count": 0, "api_calls": 0})
        else:
            self._send_json({"error": "not found"}, 404)

    def do_POST(self):
        if self.path == "/api/chars":
            from config import load_config
            from core.character_manager import CharacterManager
            cfg = load_config()
            cm = CharacterManager(cfg.paths["characters_dir"])
            self._send_json({"chars": cm.list_characters()})
        elif self.path == "/api/test/prompt":
            from config import load_config
            from core.character_manager import CharacterManager
            from core.prompt_builder import PromptBuilder
            from core.models import UserProfile
            body = self._read_body()
            cfg = load_config()
            cm = CharacterManager(cfg.paths["characters_dir"])
            card = None
            cid = body.get("char_id", "")
            for c in cm.list_characters():
                if c["id"] == cid or c["name"] == cid:
                    card = cm.get_character(c["id"])
                    break
            if not card:
                self._send_json({"error": "角色不存在: " + cid})
                return
            pb = PromptBuilder()
            profile = UserProfile(user_id="debug")
            cmem = profile.get_or_create_char_memory(card.name)
            prompt = pb.build_system_prompt(character=card, user_id="debug", profile=profile, char_memory=cmem, user_message=body.get("message", ""))
            self._send_json({"status": "ok", "prompt": prompt, "length": len(prompt), "char_name": card.name, "time": "0.1s"})
        elif self.path == "/api/test/memory":
            from core.memory_parser import extract_and_parse
            body = self._read_body()
            block, clean = extract_and_parse(body.get("text", ""))
            self._send_json({"status": "ok", "clean_text": clean, "has_memory": block is not None, "memory": block.model_dump(exclude_none=True) if block else None, "time": "0.1s"})
        elif self.path == "/api/test/split":
            from bot.server_bot import QQBotServer
            body = self._read_body()
            parts = QQBotServer._split_message(body.get("text", ""))
            self._send_json({"status": "ok", "parts": parts, "count": len(parts), "time": "0.1s"})
        elif self.path == "/api/test/retriever":
            from config import load_config
            from core.character_manager import CharacterManager
            from core.retriever import DialogueRetriever
            body = self._read_body()
            cfg = load_config()
            cm = CharacterManager(cfg.paths["characters_dir"])
            card = None
            cid = body.get("char_id", "")
            for c in cm.list_characters():
                if c["id"] == cid or c["name"] == cid:
                    card = cm.get_character(c["id"])
                    break
            if not card or not card.source_dialogues:
                self._send_json({"error": "该角色没有台词库"})
                return
            retriever = DialogueRetriever()
            results = retriever.retrieve(body.get("query", ""), card.source_dialogues, top_k=5)
            self._send_json({"status": "ok", "results": [{"line": r[0], "score": round(r[1], 4)} for r in results], "count": len(results), "time": "0.1s"})
        elif self.path == "/api/test/scheduler":
            from core.scheduler import parse_reminder_time
            body = self._read_body()
            result = parse_reminder_time(body.get("text", ""))
            self._send_json({"status": "ok" if result else "error", "parsed": result, "error": None if result else "无法解析", "time": "0.1s"})
        elif self.path == "/api/test/run_all":
            import unittest
            from io import StringIO
            loader = unittest.TestLoader()
            suite = loader.discover(str(_project_root / "tests"), pattern="test_core.py", top_level_dir=str(_project_root))
            result = unittest.TestResult()
            suite.run(result)
            details = []
            for test, tb in result.failures:
                details.append({"test": str(test), "status": "fail", "msg": str(tb)[:200]})
            for test, tb in result.errors:
                details.append({"test": str(test), "status": "error", "msg": str(tb)[:200]})
            self._send_json({"status": "ok", "total": result.testsRun, "passed": result.testsRun - len(result.failures) - len(result.errors), "failed": len(result.failures), "errors": len(result.errors), "details": details, "time": "0.5s"})
        elif self.path == "/api/memory/compress":
            from config import load_config
            from core.profile_manager import ProfileManager
            cfg = load_config()
            pm = ProfileManager(cfg.paths["db_path"])
            count = pm.compress_all_memories()
            self._send_json({"ok": True, "processed": count, "msg": "已压缩 " + str(count) + " 个用户的记忆"})
        elif self.path == "/api/characters":
            data = self._read_body()
            name = data.get("name", "").strip()
            if not name:
                self._send_json({"error": "name required"}, 400)
                return
            source = data.get("source", "")
            traits = data.get("traits", [])
            style = data.get("speaking_style", "")
            worldview = data.get("worldview", "")
            card = {
                "name": name, "source": source, "version": "1.0",
                "personality": {"core_traits": traits or ["待补充"], "speaking_style": style or "待补充", "habits": [], "emotional_range": ""},
                "knowledge_boundary": {"knows": [], "does_not_know": [], "worldview": worldview or ("《" + source + "》的世界" if source else "")},
                "speech_examples": [{"user": "你好", "response": "（角色的回应）"}],
                "source_dialogues": [], "greeting_style": "", "avatar_description": "",
                "relationship_with_user_default": "neutral", "development_arc": "",
                "conflict_triggers": [], "soft_spots": [],
                "forbidden": ["不能以 AI 或机器人的身份说话", "不能跳出角色身份"],
                "forbidden_words": [], "sticker_pack": [],
                "dialogue_config": {"max_length": 60, "allow_action_description": True},
            }
            char_dir = _project_root / "characters"
            char_dir.mkdir(exist_ok=True)
            short = name[:4]
            filepath = char_dir / (short + ".json")
            idx = 1
            while filepath.exists():
                filepath = char_dir / (short + "_" + str(idx) + ".json")
                idx += 1
            filepath.write_text(json.dumps(card, ensure_ascii=False, indent=2), encoding="utf-8")
            self._send_json({"ok": True, "file": str(filepath)})
        else:
            self._send_json({"error": "not found"}, 404)

    def do_DELETE(self):
        if self.path.startswith("/api/characters/"):
            cid = self.path.split("/")[-1]
            filepath = _project_root / "characters" / (cid + ".json")
            if filepath.exists():
                filepath.unlink()
                self._send_json({"ok": True})
            else:
                self._send_json({"error": "not found"}, 404)
        else:
            self._send_json({"error": "not found"}, 404)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()


def start_dashboard(host: str = "0.0.0.0", port: int = 8766):
    if not HTML_PATH.exists():
        print(f"  HTML 文件不存在: {HTML_PATH}")
        return
    server = HTTPServer((host, port), DashboardHandler)
    print(f"\n  管理面板: http://localhost:{port}")
    print(f"  Ctrl+C 停止服务\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    start_dashboard()
