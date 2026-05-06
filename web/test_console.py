"""
Echo_Bot 交互式调试控制台

用法：python web/test_console.py
访问：http://localhost:8878
"""

from __future__ import annotations

import json
import sys
import traceback
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Any

_project_root = Path(__file__).parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

HTML_PATH = _project_root / "web" / "test_console.html"


class TestConsoleHandler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, data: Any, status: int = 200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode())

    def _read(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length))

    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            html = HTML_PATH.read_text(encoding="utf-8")
            self.wfile.write(html.encode())
        else:
            self._send({"error": "not found"}, 404)

    def do_POST(self):
        import time
        t0 = time.time()
        try:
            path = self.path
            body = self._read()

            if path == "/api/chars":
                from config import load_config
                from core.character_manager import CharacterManager
                cfg = load_config()
                cm = CharacterManager(cfg.paths["characters_dir"])
                self._send({"chars": cm.list_characters()})

            elif path == "/api/test/prompt":
                from config import load_config
                from core.character_manager import CharacterManager
                from core.prompt_builder import PromptBuilder
                from core.models import UserProfile
                cfg = load_config()
                cm = CharacterManager(cfg.paths["characters_dir"])
                card = cm.get_character(body.get("char_id", ""))
                if not card:
                    self._send({"error": "角色不存在", "time": f"{time.time()-t0:.2f}s"})
                    return
                pb = PromptBuilder()
                profile = UserProfile(user_id="debug")
                cmem = profile.get_or_create_char_memory(card.name)
                extra = body.get("extra", "")
                if extra:
                    try:
                        ed = json.loads(extra)
                        if "mood" in ed:
                            cmem.emotional_history.append({"mood": ed["mood"]})
                        if "stage" in ed:
                            cmem.relationship_stage = ed["stage"]
                        if "tone" in ed:
                            cmem.last_tonal_suggestion = ed["tone"]
                    except Exception:
                        pass
                prompt = pb.build_system_prompt(
                    character=card, user_id="debug", profile=profile,
                    char_memory=cmem, user_message=body.get("message", ""),
                )
                self._send({
                    "status": "ok", "prompt": prompt, "length": len(prompt),
                    "char_name": card.name, "time": f"{time.time()-t0:.2f}s",
                })

            elif path == "/api/test/memory":
                from core.memory_parser import extract_and_parse
                block, clean = extract_and_parse(body.get("text", ""))
                self._send({
                    "status": "ok", "clean_text": clean,
                    "has_memory": block is not None,
                    "memory": block.model_dump(exclude_none=True) if block else None,
                    "time": f"{time.time()-t0:.2f}s",
                })

            elif path == "/api/test/split":
                from bot.server_bot import QQBotServer
                parts = QQBotServer._split_message(body.get("text", ""))
                self._send({
                    "status": "ok", "parts": parts, "count": len(parts),
                    "time": f"{time.time()-t0:.2f}s",
                })

            elif path == "/api/test/retriever":
                from config import load_config
                from core.character_manager import CharacterManager
                from core.retriever import DialogueRetriever
                cfg = load_config()
                cm = CharacterManager(cfg.paths["characters_dir"])
                card = cm.get_character(body.get("char_id", ""))
                if not card or not card.source_dialogues:
                    self._send({"error": "该角色没有台词库", "time": f"{time.time()-t0:.2f}s"})
                    return
                retriever = DialogueRetriever()
                results = retriever.retrieve(body.get("query", ""), card.source_dialogues, top_k=5)
                self._send({
                    "status": "ok",
                    "results": [{"line": r[0], "score": round(r[1], 4)} for r in results],
                    "count": len(results),
                    "time": f"{time.time()-t0:.2f}s",
                })

            elif path == "/api/test/profile":
                from config import load_config
                from core.profile_manager import ProfileManager
                cfg = load_config()
                pm = ProfileManager(cfg.paths["db_path"])
                user_id = body.get("user_id", "debug")
                op = body.get("op", "get")
                value = body.get("value", "")
                profile = pm.get_or_create_profile("user_" + user_id)
                if op == "add_trait" and value:
                    cm = profile.get_or_create_char_memory("all")
                    if value not in cm.observed_traits:
                        cm.observed_traits.append(value)
                    pm.save_profile(profile)
                elif op == "add_interest" and value:
                    cm = profile.get_or_create_char_memory("all")
                    if value not in cm.observed_interests:
                        cm.observed_interests.append(value)
                    pm.save_profile(profile)
                traits, interests, dislikes, convs = set(), set(), set(), 0
                for cid, cm in profile.per_character_memory.items():
                    traits.update(cm.observed_traits)
                    interests.update(cm.observed_interests)
                    dislikes.update(cm.observed_dislikes)
                    convs += cm.conversation_count
                self._send({
                    "status": "ok", "user_id": user_id,
                    "traits": sorted(traits), "interests": sorted(interests),
                    "dislikes": sorted(dislikes), "conversations": convs,
                    "time": f"{time.time()-t0:.2f}s",
                })

            elif path == "/api/test/scheduler":
                from core.scheduler import parse_reminder_time
                result = parse_reminder_time(body.get("text", ""))
                self._send({
                    "status": "ok" if result else "error",
                    "parsed": result,
                    "error": None if result else "无法解析",
                    "time": f"{time.time()-t0:.2f}s",
                })

            elif path == "/api/test/run_all":
                import unittest
                loader = unittest.TestLoader()
                suite = loader.discover(
                    str(_project_root / "tests"), pattern="test_core.py",
                    top_level_dir=str(_project_root),
                )
                result = unittest.TestResult()
                suite.run(result)
                tests_run = result.testsRun
                details = []
                for test, tb in result.failures:
                    details.append({"test": str(test), "status": "fail", "msg": str(tb)[:200]})
                for test, tb in result.errors:
                    details.append({"test": str(test), "status": "error", "msg": str(tb)[:200]})
                self._send({
                    "status": "ok",
                    "total": tests_run,
                    "passed": tests_run - len(result.failures) - len(result.errors),
                    "failed": len(result.failures),
                    "errors": len(result.errors),
                    "details": details,
                    "time": f"{time.time()-t0:.2f}s",
                })

            else:
                self._send({"error": "not found"}, 404)

        except Exception as e:
            self._send({"error": str(e), "traceback": traceback.format_exc(), "time": f"{time.time()-t0:.2f}s"}, 500)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()


def start(host: str = "0.0.0.0", port: int = 8878):
    print(f"\n  Echo_Bot 调试控制台")
    print(f"  {'='*40}")
    print(f"  访问地址: http://localhost:{port}")
    print(f"  Ctrl+C 停止服务")
    print(f"  {'='*40}\n")
    HTTPServer((host, port), TestConsoleHandler).serve_forever()


if __name__ == "__main__":
    start()
