"""
Echo_Bot 管理面板 — 轻量 Web UI

用法：
  python web/dashboard.py
  或作为模块引入，与 Bot 同进程运行

默认访问：http://localhost:8766
"""

from __future__ import annotations

import json
import logging
import os
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# 项目根目录
_PROJECT_ROOT = Path(__file__).parent.parent

# HTML 模板
HTML_PAGE = """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Echo_Bot 管理面板</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, 'Segoe UI', sans-serif; background: #f5f5f5; color: #333; }
.header { background: linear-gradient(135deg, #667eea, #764ba2); color: #fff; padding: 20px 30px; }
.header h1 { font-size: 22px; }
.header p { opacity: 0.85; font-size: 14px; margin-top: 4px; }
.container { max-width: 1000px; margin: 0 auto; padding: 20px; }
.card { background: #fff; border-radius: 10px; padding: 20px; margin-bottom: 20px; box-shadow: 0 2px 8px rgba(0,0,0,0.08); }
.card h2 { font-size: 16px; margin-bottom: 12px; color: #555; border-bottom: 1px solid #eee; padding-bottom: 8px; }
.char-list { display: grid; gap: 12px; }
.char-item { display: flex; align-items: center; justify-content: space-between; padding: 12px 16px; background: #fafafa; border-radius: 8px; border: 1px solid #eee; }
.char-item .name { font-weight: 600; }
.char-item .source { color: #888; font-size: 13px; margin-left: 8px; }
.char-item .traits { color: #666; font-size: 12px; }
.char-item .actions button { margin-left: 8px; padding: 4px 12px; border: none; border-radius: 4px; cursor: pointer; }
.btn-edit { background: #667eea; color: #fff; }
.btn-del { background: #e74c3c; color: #fff; }
.btn { padding: 8px 20px; border: none; border-radius: 6px; cursor: pointer; font-size: 14px; }
.btn-primary { background: #667eea; color: #fff; }
.status-dot { display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 6px; }
.status-online { background: #2ecc71; }
.status-offline { background: #e74c3c; }
.edit-form label { display: block; margin: 10px 0 4px; font-size: 13px; color: #666; }
.edit-form input, .edit-form textarea { width: 100%; padding: 8px; border: 1px solid #ddd; border-radius: 4px; font-size: 14px; }
.edit-form textarea { min-height: 80px; resize: vertical; }
.hidden { display: none; }
.nav { display: flex; gap: 10px; margin-bottom: 20px; }
.nav a { padding: 8px 16px; background: #fff; border-radius: 6px; text-decoration: none; color: #555; font-size: 14px; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }
.nav a.active { background: #667eea; color: #fff; }
.modal { position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.4); display: flex; align-items: center; justify-content: center; z-index: 999; }
.modal-content { background: #fff; border-radius: 12px; padding: 24px; width: 90%; max-width: 600px; max-height: 80vh; overflow-y: auto; }
</style>
</head>
<body>
<div class="header">
  <h1>Echo_Bot 管理面板</h1>
  <p id="status-text">加载中...</p>
</div>
<div class="container">
  <div class="nav">
    <a href="#" class="active" onclick="showTab('characters')">角色管理</a>
    <a href="#" onclick="showTab('settings')">系统设置</a>
    <a href="#" onclick="showTab('plugins')">插件管理</a>
  </div>

  <div id="tab-characters">
    <div class="card">
      <h2>角色列表</h2>
      <div id="char-list" class="char-list"></div>
      <div style="margin-top:12px"><button class="btn btn-primary" onclick="openEditor()">+ 添加角色</button></div>
    </div>
  </div>

  <div id="tab-settings" class="hidden">
    <div class="card">
      <h2>系统设置</h2>
      <div id="sys-info"></div>
    </div>
  </div>

  <div id="tab-plugins" class="hidden">
    <div class="card">
      <h2>已加载的插件</h2>
      <div id="plugin-list"></div>
    </div>
  </div>
</div>

<!-- 编辑器弹窗 -->
<div id="editor-modal" class="modal hidden" onclick="closeEditor(event)">
  <div class="modal-content" onclick="event.stopPropagation()">
    <h2 id="editor-title">编辑角色</h2>
    <div class="edit-form" id="editor-form"></div>
    <div style="margin-top:16px;text-align:right;gap:8px;display:flex;justify-content:flex-end">
      <button class="btn" onclick="closeEditor()">取消</button>
      <button class="btn btn-primary" onclick="saveChar()">保存</button>
    </div>
  </div>
</div>

<script>
let chars = [];

async function api(url, method='GET', body=null) {
  const opt = { method, headers: {'Content-Type':'application/json'} };
  if (body) opt.body = JSON.stringify(body);
  const r = await fetch(url, opt);
  return r.json();
}

async function load() {
  const status = await api('/api/status');
  document.getElementById('status-text').innerHTML = \`<span class="status-dot \${status.online?'status-online':'status-offline'}"></span>\${status.online ? '运行中' : '离线'} | 角色: \${status.char_count} | API调用: \${status.api_calls}\`;

  const data = await api('/api/characters');
  chars = data;
  renderList();

  const sysData = await api('/api/system');
  document.getElementById('sys-info').innerHTML = \`<pre style="font-size:13px">\${JSON.stringify(sysData, null, 2)}</pre>\`;

  const plugins = await api('/api/plugins');
  document.getElementById('plugin-list').innerHTML = plugins.length ?
    plugins.map(p => \`<div class="char-item"><span class="name">\${p.name}</span><span class="source">v\${p.version}</span><span style="color:#888;font-size:13px">\${p.description}</span></div>\`).join('') :
    '<p style="color:#888">暂无插件</p>';
}

function renderList() {
  const el = document.getElementById('char-list');
  el.innerHTML = chars.map(c => \`<div class="char-item">
    <div><span class="name">\${c.name}</span><span class="source">\${c.source||''}</span>
    <div class="traits">\${(c.traits||[]).slice(0,4).join('、')}</div></div>
    <div class="actions">
      <button class="btn-edit" onclick="openEditor('\${c.id}')">编辑</button>
      <button class="btn-del" onclick="delChar('\${c.id}')">删除</button>
    </div>
  </div>\`).join('');
}

async function openEditor(id) {
  const modal = document.getElementById('editor-modal');
  modal.classList.remove('hidden');
  const title = document.getElementById('editor-title');

  let data = { name:'', source:'', personality:{core_traits:['待补充'],speaking_style:'待补充'} };
  if (id) {
    title.textContent = '编辑角色';
    data = chars.find(c => c.id === id) || data;
  } else {
    title.textContent = '添加角色';
  }

  document.getElementById('editor-form').innerHTML = \`
    <label>角色名 <input id="f-name" value="\${data.name||''}"></label>
    <label>出处 <input id="f-source" value="\${data.source||''}"></label>
    <label>性格标签（逗号分隔） <input id="f-traits" value="\${(data.personality?.core_traits||[]).join('、')}"></label>
    <label>说话风格 <textarea id="f-style">\${data.personality?.speaking_style||''}</textarea></label>
    <label>世界观 <textarea id="f-worldview">\${data.knowledge_boundary?.worldview||''}</textarea></label>
  \`;
  document._editId = id;
}

async function saveChar() {
  const id = document._editId;
  const body = {
    name: document.getElementById('f-name').value,
    source: document.getElementById('f-source').value,
    traits: document.getElementById('f-traits').value.split(/[,，、]/).map(s=>s.trim()).filter(Boolean),
    speaking_style: document.getElementById('f-style').value,
    worldview: document.getElementById('f-worldview').value,
  };
  if (!body.name) { alert('角色名不能为空'); return; }
  await api(id ? '/api/characters/'+id : '/api/characters', 'POST', body);
  closeEditor();
  load();
}

async function delChar(id) {
  if (!confirm('确认删除此角色？')) return;
  await api('/api/characters/'+id, 'DELETE');
  load();
}

function closeEditor(e) {
  document.getElementById('editor-modal').classList.add('hidden');
}

function showTab(name) {
  document.querySelectorAll('[id^="tab-"]').forEach(e => e.classList.add('hidden'));
  document.getElementById('tab-'+name).classList.remove('hidden');
  document.querySelectorAll('.nav a').forEach(a => a.classList.remove('active'));
  document.querySelectorAll('.nav a')[['characters','settings','plugins'].indexOf(name)].classList.add('active');
}

load();
</script>
</body>
</html>"""


class DashboardHandler(BaseHTTPRequestHandler):
    """HTTP 请求处理"""

    def log_message(self, format, *args):
        logger.debug(format, *args)

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
        body = self.rfile.read(length)
        return json.loads(body)

    def _load_characters(self) -> list[dict]:
        char_dir = _PROJECT_ROOT / "characters"
        if not char_dir.exists():
            return []
        chars = []
        for f in sorted(char_dir.glob("*.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                cid = f.stem
                traits = data.get("personality", {}).get("core_traits", [])
                chars.append({
                    "id": cid, "name": data.get("name", cid),
                    "source": data.get("source", ""),
                    "traits": traits,
                    "personality": data.get("personality", {}),
                    "knowledge_boundary": data.get("knowledge_boundary", {}),
                })
            except Exception as e:
                chars.append({"id": f.stem, "name": f.stem, "error": str(e)})
        return chars

    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML_PAGE.encode())
        elif self.path == "/api/characters":
            self._send_json(self._load_characters())
        elif self.path == "/api/system":
            self._send_json({
                "version": "1.0.0",
                "python": sys.version,
                "characters_dir": str(_PROJECT_ROOT / "characters"),
                "data_dir": str(_PROJECT_ROOT / "data"),
            })
        elif self.path == "/api/plugins":
            self._send_json([])
        elif self.path == "/api/status":
            from config import get_config
            try:
                cfg = get_config()
                self._send_json({
                    "online": True,
                    "char_count": len(self._load_characters()),
                    "api_calls": 0,
                    "provider": cfg.llm.get("provider", ""),
                    "model": cfg.llm.get("model", ""),
                })
            except Exception:
                self._send_json({"online": False, "char_count": 0, "api_calls": 0})
        else:
            self._send_json({"error": "not found"}, 404)

    def do_POST(self):
        if self.path == "/api/characters":
            data = self._read_body()
            name = data.get("name", "").strip()
            if not name:
                self._send_json({"error": "name required"}, 400)
                return
            # 生成角色卡 JSON
            source = data.get("source", "")
            traits = data.get("traits", [])
            style = data.get("speaking_style", "")
            worldview = data.get("worldview", "")

            card = {
                "name": name,
                "source": source,
                "version": "1.0",
                "personality": {
                    "core_traits": traits if traits else ["待补充"],
                    "speaking_style": style or "待补充",
                    "habits": [],
                    "emotional_range": "",
                },
                "knowledge_boundary": {
                    "knows": [],
                    "does_not_know": [],
                    "worldview": worldview or f"《{source}》的世界" if source else "",
                },
                "speech_examples": [
                    {"user": "你好", "response": "（角色的回应）"}
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
                "dialogue_config": {"max_length": 60, "allow_action_description": True},
                "sticker_pack": [],
            }

            # 写文件
            char_dir = _PROJECT_ROOT / "characters"
            char_dir.mkdir(exist_ok=True)
            filepath = char_dir / f"{name[:4]}.json"

            if not self.path.endswith("/" + name[:4]):  # POST vs 更新
                idx = 1
                while filepath.exists():
                    filepath = char_dir / f"{name[:4]}_{idx}.json"
                    idx += 1

            filepath.write_text(json.dumps(card, ensure_ascii=False, indent=2), encoding="utf-8")
            self._send_json({"ok": True, "file": str(filepath)})
        else:
            self._send_json({"error": "not found"}, 404)

    def do_DELETE(self):
        if self.path.startswith("/api/characters/"):
            cid = self.path.split("/")[-1]
            char_dir = _PROJECT_ROOT / "characters"
            filepath = char_dir / f"{cid}.json"
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
    """启动管理面板"""
    server = HTTPServer((host, port), DashboardHandler)
    logger.info("管理面板启动: http://%s:%s", host, port)
    print(f"\n  管理面板: http://{host if host != '0.0.0.0' else 'localhost'}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    sys.path.insert(0, str(_PROJECT_ROOT))
    start_dashboard()
