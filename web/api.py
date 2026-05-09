"""
Echo_Bot API 服务 — FastAPI

启动：uvicorn web.api:app --host 0.0.0.0 --port 8766
文档：http://localhost:8766/docs
"""

from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path
from typing import Any, Optional

# 确保项目根目录可导入
_project_root = Path(__file__).parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("api")

app = FastAPI(title="Echo_Bot API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ===================================================================
# 静态文件服务
# ===================================================================

FRONTEND_DIR = _project_root / "web" / "frontend"


def _load_characters() -> list[dict]:
    """加载角色列表"""
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
        except Exception:
            chars.append({"id": f.stem, "name": f.stem})
    return chars


# ===================================================================
# API 端点
# ===================================================================

@app.get("/api/status")
def get_status():
    from config import get_config
    try:
        cfg = get_config()
        return {"online": True, "char_count": len(_load_characters()), "provider": cfg.llm.get("provider", ""), "model": cfg.llm.get("model", "")}
    except Exception:
        return {"online": False, "char_count": 0}


@app.get("/api/characters")
def get_characters():
    return _load_characters()


@app.get("/api/system")
def get_system():
    return {"version": "2.0.0", "python": sys.version.split()[0], "characters_dir": str(_project_root / "characters"), "data_dir": str(_project_root / "data")}


# ---- 测试端点 ----

class PromptTest(BaseModel):
    char_id: str = ""
    message: str = "你好"
    extra: str = ""


@app.post("/api/test/prompt")
def test_prompt(body: PromptTest):
    from core.character_manager import CharacterManager
    from core.prompt_builder import PromptBuilder
    from core.models import UserProfile
    from config import load_config
    cfg = load_config()
    cm = CharacterManager(cfg.paths["characters_dir"])
    card = None
    for c in cm.list_characters():
        if c["id"] == body.char_id or c["name"] == body.char_id:
            card = cm.get_character(c["id"])
            break
    if not card:
        raise HTTPException(404, "角色不存在")
    pb = PromptBuilder()
    profile = UserProfile(user_id="debug")
    cmem = profile.get_or_create_char_memory(card.name)
    if body.extra:
        try:
            ed = json.loads(body.extra)
            if "mood" in ed:
                cmem.emotional_history.append({"mood": ed["mood"]})
            if "stage" in ed:
                cmem.relationship_stage = ed["stage"]
        except Exception:
            pass
    prompt = pb.build_system_prompt(character=card, user_id="debug", profile=profile, char_memory=cmem, user_message=body.message)
    return {"status": "ok", "prompt": prompt, "length": len(prompt), "char_name": card.name}


class MemoryTest(BaseModel):
    text: str = ""


@app.post("/api/test/memory")
def test_memory(body: MemoryTest):
    from core.memory_parser import extract_and_parse
    block, clean = extract_and_parse(body.text)
    return {"status": "ok", "clean_text": clean, "has_memory": block is not None, "memory": block.model_dump(exclude_none=True) if block else None}


class SplitTest(BaseModel):
    text: str = ""


@app.post("/api/test/split")
def test_split(body: SplitTest):
    from bot.server_bot import QQBotServer
    parts = QQBotServer._split_message(body.text)
    return {"status": "ok", "parts": parts, "count": len(parts)}


class QueryTest(BaseModel):
    char_id: str = ""
    query: str = "你好"


@app.post("/api/test/retriever")
def test_retriever(body: QueryTest):
    from core.character_manager import CharacterManager
    from core.retriever import DialogueRetriever
    from config import load_config
    cfg = load_config()
    cm = CharacterManager(cfg.paths["characters_dir"])
    card = None
    for c in cm.list_characters():
        if c["id"] == body.char_id or c["name"] == body.char_id:
            card = cm.get_character(c["id"])
            break
    if not card or not card.source_dialogues:
        raise HTTPException(404, "该角色没有台词库")
    retriever = DialogueRetriever()
    results = retriever.retrieve(body.query, card.source_dialogues, top_k=5)
    return {"status": "ok", "results": [{"line": r[0], "score": round(r[1], 4)} for r in results], "count": len(results)}


class SchedulerTest(BaseModel):
    text: str = ""


@app.post("/api/test/scheduler")
def test_scheduler(body: SchedulerTest):
    from core.scheduler import parse_reminder_time
    result = parse_reminder_time(body.text)
    return {"status": "ok" if result else "error", "parsed": result}


@app.post("/api/test/run_all")
def run_all_tests():
    import unittest
    loader = unittest.TestLoader()
    suite = loader.discover(str(_project_root / "tests"), pattern="test_core.py", top_level_dir=str(_project_root))
    result = unittest.TestResult()
    suite.run(result)
    details = []
    for test, tb in result.failures:
        details.append({"test": str(test), "status": "fail", "msg": str(tb)[:200]})
    for test, tb in result.errors:
        details.append({"test": str(test), "status": "error", "msg": str(tb)[:200]})
    return {
        "status": "ok", "total": result.testsRun,
        "passed": result.testsRun - len(result.failures) - len(result.errors),
        "failed": len(result.failures), "errors": len(result.errors),
        "details": details,
    }


# ---- 角色管理 ----

class CharCreate(BaseModel):
    name: str
    source: str = ""
    traits: list[str] = []
    speaking_style: str = ""
    worldview: str = ""


@app.post("/api/characters")
def create_character(body: CharCreate):
    if not body.name:
        raise HTTPException(400, "角色名不能为空")
    card = {
        "name": body.name, "source": body.source, "version": "1.0",
        "personality": {"core_traits": body.traits or ["待补充"], "speaking_style": body.speaking_style or "待补充", "habits": [], "emotional_range": ""},
        "knowledge_boundary": {"knows": [], "does_not_know": [], "worldview": body.worldview or ""},
        "speech_examples": [{"user": "你好", "response": "（角色的回应）"}],
        "source_dialogues": [], "greeting_style": "", "avatar_description": "",
        "relationship_with_user_default": "neutral", "development_arc": "",
        "conflict_triggers": [], "soft_spots": [],
        "forbidden": ["不能以AI身份说话"], "forbidden_words": [],
        "dialogue_config": {"max_length": 60},
    }
    char_dir = _project_root / "characters"
    char_dir.mkdir(exist_ok=True)
    path = char_dir / f"{body.name[:4]}.json"
    path.write_text(json.dumps(card, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True, "file": str(path)}


@app.delete("/api/characters/{char_id}")
def delete_character(char_id: str):
    path = _project_root / "characters" / f"{char_id}.json"
    if not path.exists():
        raise HTTPException(404, "角色不存在")
    path.unlink()
    return {"ok": True}


# ---- WebSocket ----

class ConnectionManager:
    def __init__(self):
        self.active: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.append(ws)

    def disconnect(self, ws: WebSocket):
        if ws in self.active:
            self.active.remove(ws)


manager = ConnectionManager()


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            await websocket.send_text(f"收到: {data}")
    except WebSocketDisconnect:
        manager.disconnect(websocket)


# ---- 前端 ----

@app.get("/")
async def serve_frontend():
    index = FRONTEND_DIR / "index.html"
    if index.exists():
        return HTMLResponse(index.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Echo_Bot API</h1><p>前端未构建。运行 cd web/frontend && npm run build</p><p><a href='/docs'>API 文档</a></p>")


# ===================================================================
# 直接启动
# ===================================================================

if __name__ == "__main__":
    import uvicorn
    print(f"  Echo_Bot API: http://localhost:8766")
    print(f"  API 文档:     http://localhost:8766/docs")
    uvicorn.run(app, host="0.0.0.0", port=8766)
