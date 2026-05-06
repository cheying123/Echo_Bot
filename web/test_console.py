"""
Echo_Bot 交互式调试控制台

直接在浏览器中测试各个模块的功能。

用法：python web/test_console.py
访问：http://localhost:8878
"""

from __future__ import annotations

import json
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Any

# 确保项目根目录可导入
_project_root = Path(__file__).parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import traceback

HTML_PAGE = """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Echo_Bot 调试控制台</title>
<style>
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family:'Segoe UI',system-ui,-apple-system,sans-serif; background:#f1f5f9; color:#1e293b; }
.header { background:linear-gradient(135deg,#6366f1,#8b5cf6); color:#fff; padding:16px 24px; display:flex; align-items:center; gap:12px; }
.header h1 { font-size:18px; }
.header .sub { opacity:0.8; font-size:13px; }
.container { max-width:1200px; margin:0 auto; padding:16px; display:grid; grid-template-columns:300px 1fr; gap:16px; }
.sidebar { background:#fff; border-radius:8px; padding:12px; height:fit-content; box-shadow:0 1px 3px rgba(0,0,0,0.06); }
.sidebar button { display:block; width:100%; padding:10px 14px; margin-bottom:4px; border:none; border-radius:6px; cursor:pointer; font-size:13px; text-align:left; background:transparent; color:#475569; }
.sidebar button:hover { background:#f1f5f9; }
.sidebar button.active { background:#6366f1; color:#fff; }
.main { background:#fff; border-radius:8px; min-height:500px; box-shadow:0 1px 3px rgba(0,0,0,0.06); }
.tab { display:none; padding:20px; }
.tab.active { display:block; }
.tab h2 { font-size:16px; margin-bottom:12px; color:#334155; }
.form-row { margin-bottom:12px; }
.form-row label { display:block; font-size:12px; color:#64748b; margin-bottom:4px; }
.form-row input,.form-row textarea,.form-row select { width:100%; padding:8px 10px; border:1px solid #e2e8f0; border-radius:6px; font-size:13px; font-family:inherit; }
.form-row textarea { min-height:80px; resize:vertical; font-family:'Cascadia Code','Fira Code',monospace; font-size:12px; }
.form-row .hint { font-size:11px; color:#94a3b8; margin-top:2px; }
.btn { padding:8px 20px; border:none; border-radius:6px; cursor:pointer; font-size:13px; }
.btn-primary { background:#6366f1; color:#fff; }
.btn-primary:hover { background:#4f46e5; }
.result { margin-top:16px; border:1px solid #e2e8f0; border-radius:8px; overflow:hidden; }
.result-header { padding:8px 12px; background:#f8fafc; font-size:12px; color:#64748b; display:flex; justify-content:space-between; }
.result-body { padding:12px; font-family:'Cascadia Code','Fira Code',monospace; font-size:12px; white-space:pre-wrap; overflow-x:auto; max-height:400px; overflow-y:auto; }
.result-body.json { }
.result-success { border-color:#22c55e; }
.result-success .result-header { background:#f0fdf4; color:#166534; }
.result-error { border-color:#ef4444; }
.result-error .result-header { background:#fef2f2; color:#991b1b; }
.loading { opacity:0.5; pointer-events:none; }
@media(max-width:768px){ .container{grid-template-columns:1fr;} }
</style>
</head>
<body>
<div class="header">
  <h1>Echo_Bot 调试控制台</h1>
  <span class="sub">交互式模块测试</span>
</div>
<div class="container">
  <div class="sidebar">
    <button class="active" onclick="switchTab('prompt')">提示词构建</button>
    <button onclick="switchTab('memory')">MEMORY 解析</button>
    <button onclick="switchTab('split')">消息拆分</button>
    <button onclick="switchTab('retriever')">台词检索</button>
    <button onclick="switchTab('profile')">用户画像</button>
    <button onclick="switchTab('scheduler')">时间解析</button>
    <button onclick="switchTab('fulltest')">全量测试</button>
  </div>
  <div class="main">
    <!-- 提示词构建 -->
    <div class="tab active" id="tab-prompt">
      <h2>提示词构建</h2>
      <div class="form-row">
        <label>角色</label>
        <select id="prompt-char"></select>
      </div>
      <div class="form-row">
        <label>用户消息</label>
        <textarea id="prompt-msg" placeholder="输入用户消息...">你好</textarea>
      </div>
      <div class="form-row">
        <label>额外参数（JSON）</label>
        <input id="prompt-extra" placeholder='{"mood": "positive"}'>
        <div class="hint">可选：mood(情绪), stage(关系阶段), tone(语气建议)</div>
      </div>
      <button class="btn btn-primary" onclick="testPrompt()">构建提示词</button>
      <div id="result-prompt"></div>
    </div>

    <!-- MEMORY 解析 -->
    <div class="tab" id="tab-memory">
      <h2>MEMORY 解析</h2>
      <div class="form-row">
        <label>AI 回复文本（含 MEMORY 块）</label>
        <textarea id="memory-input" rows="6">你好呀，今天心情怎么样？
<<<MEMORY>>>
{"user_id":"test","observations":{"mood":"positive","new_traits":["喜欢自嘲"],"interests_mentioned":["动漫"],"speech_pattern":"简短直接"},"relationship":{"trust_signal":"提升","affection_signal":"维持"},"strategy_adjustments":{"next_tone":"可以更随意","topics_to_explore":["动漫"]}}
<<<END_MEMORY>>></textarea>
      </div>
      <button class="btn btn-primary" onclick="testMemory()">解析 MEMORY</button>
      <div id="result-memory"></div>
    </div>

    <!-- 消息拆分 -->
    <div class="tab" id="tab-split">
      <h2>消息拆分测试</h2>
      <div class="form-row">
        <label>输入文本</label>
        <textarea id="split-input" rows="4">指挥官，早上好。[pause]*放下手中的数据板* 今天有什么安排吗？我们一起去训练场吧。下午还有新的战术分析会。</textarea>
        <div class="hint">用 [pause] 标记停顿，或直接用句号自动拆分</div>
      </div>
      <button class="btn btn-primary" onclick="testSplit()">测试拆分</button>
      <div id="result-split"></div>
    </div>

    <!-- 台词检索 -->
    <div class="tab" id="tab-retriever">
      <h2>台词检索</h2>
      <div class="form-row">
        <label>角色</label>
        <select id="ret-char"></select>
      </div>
      <div class="form-row">
        <label>查询内容</label>
        <input id="ret-query" value="今天心情不好">
      </div>
      <button class="btn btn-primary" onclick="testRetriever()">检索</button>
      <div id="result-retriever"></div>
    </div>

    <!-- 用户画像 -->
    <div class="tab" id="tab-profile">
      <h2>用户画像操作</h2>
      <div class="form-row">
        <label>用户 ID</label>
        <input id="profile-uid" value="test_user_001">
      </div>
      <div class="form-row">
        <label>操作</label>
        <select id="profile-op">
          <option value="get">查看画像</option>
          <option value="add_trait">添加性格标签</option>
          <option value="add_interest">添加兴趣</option>
        </select>
      </div>
      <div class="form-row" id="profile-value-row">
        <label>值</label>
        <input id="profile-value" placeholder="例如：幽默">
      </div>
      <button class="btn btn-primary" onclick="testProfile()">执行</button>
      <div id="result-profile"></div>
    </div>

    <!-- 时间解析 -->
    <div class="tab" id="tab-scheduler">
      <h2>提醒时间解析</h2>
      <div class="form-row">
        <label>输入时间文本</label>
        <input id="sched-input" value="明天早上8点" style="font-size:16px;padding:12px;">
        <div class="hint">支持：明天早上8点、今天下午3点、5分钟后、后天、2026-05-05 08:00</div>
      </div>
      <button class="btn btn-primary" onclick="testScheduler()">解析时间</button>
      <div id="result-scheduler"></div>
    </div>

    <!-- 全量测试 -->
    <div class="tab" id="tab-fulltest">
      <h2>全量测试</h2>
      <p style="color:#64748b;font-size:13px;margin-bottom:12px;">运行所有模块的单元测试，查看通过/失败情况。</p>
      <button class="btn btn-primary" onclick="runFullTest()">运行全部测试</button>
      <div id="result-fulltest"></div>
    </div>
  </div>
</div>

<script>
function switchTab(name) {
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.sidebar button').forEach(b => b.classList.remove('active'));
  document.getElementById('tab-'+name).classList.add('active');
  event.target.classList.add('active');
  // 加载角色列表
  if (name === 'prompt' || name === 'retriever') loadChars(name);
}
async function api(url, body) {
  const r = await fetch(url, {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  return r.json();
}
function showResult(containerId, data, status) {
  const el = document.getElementById(containerId);
  const ok = status === 'ok' || (data && !data.error);
  el.innerHTML = \`<div class="result \${ok?'result-success':'result-error'}">
    <div class="result-header"><span>\${ok ? '成功' : '失败'}</span><span>\${data.time||''}</span></div>
    <div class="result-body json">\${escapeHtml(typeof data === 'string' ? data : JSON.stringify(data, null, 2))}</div>
  </div>\`;
}
function escapeHtml(t) { return t.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }

async function loadChars(from) {
  const d = await api('/api/chars', {});
  const sel = document.getElementById(from+'-char');
  if (!sel) return;
  sel.innerHTML = (d.chars||[]).map(c => \`<option value="\${c.id}">\${c.name}</option>\`).join('');
}
async function testPrompt() {
  const r = await api('/api/test/prompt', {
    char_id: document.getElementById('prompt-char').value,
    message: document.getElementById('prompt-msg').value,
    extra: document.getElementById('prompt-extra').value,
  });
  showResult('result-prompt', r, r.status);
}
async function testMemory() {
  const r = await api('/api/test/memory', {text: document.getElementById('memory-input').value});
  showResult('result-memory', r, r.status);
}
async function testSplit() {
  const r = await api('/api/test/split', {text: document.getElementById('split-input').value});
  showResult('result-split', r, r.status);
}
async function testRetriever() {
  const r = await api('/api/test/retriever', {
    char_id: document.getElementById('ret-char').value,
    query: document.getElementById('ret-query').value,
  });
  showResult('result-retriever', r, r.status);
}
async function testProfile() {
  const r = await api('/api/test/profile', {
    user_id: document.getElementById('profile-uid').value,
    op: document.getElementById('profile-op').value,
    value: document.getElementById('profile-value').value,
  });
  showResult('result-profile', r, r.status);
}
async function testScheduler() {
  const r = await api('/api/test/scheduler', {text: document.getElementById('sched-input').value});
  showResult('result-scheduler', r, r.status);
}
async function runFullTest() {
  const btn = event.target; btn.disabled = true; btn.textContent = '运行中...';
  try {
    const r = await api('/api/test/run_all', {});
    showResult('result-fulltest', r, r.status);
  } finally { btn.disabled = false; btn.textContent = '运行全部测试'; }
}
// 初始化
loadChars('prompt');
loadChars('retriever');
</script>
</body>
</html>"""


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
            self.wfile.write(HTML_PAGE.encode())
        else:
            self._send({"error": "not found"}, 404)

    def do_POST(self):
        import time
        start = time.time()
        try:
            if self.path == "/api/chars":
                self._handle_chars()
            elif self.path == "/api/test/prompt":
                self._handle_prompt()
            elif self.path == "/api/test/memory":
                self._handle_memory()
            elif self.path == "/api/test/split":
                self._handle_split()
            elif self.path == "/api/test/retriever":
                self._handle_retriever()
            elif self.path == "/api/test/profile":
                self._handle_profile()
            elif self.path == "/api/test/scheduler":
                self._handle_scheduler()
            elif self.path == "/api/test/run_all":
                self._handle_run_all()
            else:
                self._send({"error": "not found"}, 404)
        except Exception as e:
            self._send({"error": str(e), "traceback": traceback.format_exc(), "time": f"{time.time()-start:.2f}s"}, 500)

    def _handle_chars(self):
        from config import load_config
        from core.character_manager import CharacterManager
        cfg = load_config()
        cm = CharacterManager(cfg.paths["characters_dir"])
        self._send({"chars": cm.list_characters()})

    def _handle_prompt(self):
        import time
        t = time.time()
        body = self._read()
        from config import load_config
        from core.character_manager import CharacterManager
        from core.prompt_builder import PromptBuilder
        from core.models import UserProfile, PerCharacterMemory

        cfg = load_config()
        cm = CharacterManager(cfg.paths["characters_dir"])
        card = cm.get_character(body.get("char_id", ""))
        if not card:
            self._send({"error": "角色不存在", "time": f"{time.time()-t:.2f}s"})
            return

        pb = PromptBuilder()
        profile = UserProfile(user_id="debug")
        cmem = profile.get_or_create_char_memory(card.name)

        # 处理额外参数
        extra = body.get("extra", "")
        if extra:
            try:
                extra_data = json.loads(extra)
                if "mood" in extra_data:
                    cmem.emotional_history.append({"mood": extra_data["mood"]})
                if "stage" in extra_data:
                    cmem.relationship_stage = extra_data["stage"]
                if "tone" in extra_data:
                    cmem.last_tonal_suggestion = extra_data["tone"]
            except Exception:
                pass

        prompt = pb.build_system_prompt(
            character=card,
            user_id="debug",
            profile=profile,
            char_memory=cmem,
            user_message=body.get("message", ""),
        )
        self._send({
            "status": "ok",
            "prompt": prompt,
            "length": len(prompt),
            "char_name": card.name,
            "time": f"{time.time()-t:.2f}s",
        })

    def _handle_memory(self):
        import time
        t = time.time()
        body = self._read()
        from core.memory_parser import extract_and_parse
        block, clean = extract_and_parse(body.get("text", ""))
        self._send({
            "status": "ok",
            "clean_text": clean,
            "has_memory": block is not None,
            "memory": block.model_dump(exclude_none=True) if block else None,
            "time": f"{time.time()-t:.2f}s",
        })

    def _handle_split(self):
        import time
        t = time.time()
        body = self._read()
        from bot.server_bot import QQBotServer
        parts = QQBotServer._split_message(body.get("text", ""))
        self._send({
            "status": "ok",
            "parts": parts,
            "count": len(parts),
            "time": f"{time.time()-t:.2f}s",
        })

    def _handle_retriever(self):
        import time
        t = time.time()
        body = self._read()
        from config import load_config
        from core.character_manager import CharacterManager
        cfg = load_config()
        cm = CharacterManager(cfg.paths["characters_dir"])
        card = cm.get_character(body.get("char_id", ""))
        if not card or not card.source_dialogues:
            self._send({"error": "该角色没有台词库", "time": f"{time.time()-t:.2f}s"})
            return

        from core.retriever import DialogueRetriever
        retriever = DialogueRetriever()
        results = retriever.retrieve(body.get("query", ""), card.source_dialogues, top_k=5)
        self._send({
            "status": "ok",
            "results": [{"line": r[0], "score": round(r[1], 4)} for r in results],
            "count": len(results),
            "time": f"{time.time()-t:.2f}s",
        })

    def _handle_profile(self):
        import time
        t = time.time()
        body = self._read()
        from config import load_config
        from core.profile_manager import ProfileManager
        import tempfile, os

        cfg = load_config()
        pm = ProfileManager(cfg.paths["db_path"])
        user_id = body.get("user_id", "debug")
        op = body.get("op", "get")
        value = body.get("value", "")

        profile = pm.get_or_create_profile(f"user_{user_id}")

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

        # 合并所有角色数据
        traits = set()
        interests = set()
        dislikes = set()
        convs = 0
        for cid, cm in profile.per_character_memory.items():
            traits.update(cm.observed_traits)
            interests.update(cm.observed_interests)
            dislikes.update(cm.observed_dislikes)
            convs += cm.conversation_count

        self._send({
            "status": "ok",
            "user_id": user_id,
            "traits": sorted(traits),
            "interests": sorted(interests),
            "dislikes": sorted(dislikes),
            "conversations": convs,
            "per_character": {k: {"traits": v.observed_traits, "interests": v.observed_interests, "convs": v.conversation_count} for k, v in profile.per_character_memory.items()},
            "time": f"{time.time()-t:.2f}s",
        })

    def _handle_scheduler(self):
        import time
        t = time.time()
        body = self._read()
        from core.scheduler import parse_reminder_time
        result = parse_reminder_time(body.get("text", ""))
        self._send({
            "status": "ok" if result else "error",
            "parsed": result,
            "error": "无法解析" if not result else None,
            "time": f"{time.time()-t:.2f}s",
        })

    def _handle_run_all(self):
        import time
        t = time.time()
        import unittest
        from io import StringIO

        loader = unittest.TestLoader()
        suite = loader.discover(
            str(_project_root / "tests"),
            pattern="test_core.py",
            top_level_dir=str(_project_root),
        )

        result = unittest.TestResult()
        suite.run(result)

        tests_run = result.testsRun
        passed = tests_run - len(result.failures) - len(result.errors)

        details = []
        for test, tb in result.failures:
            details.append({"test": str(test), "status": "fail", "msg": str(tb)[:200]})
        for test, tb in result.errors:
            details.append({"test": str(test), "status": "error", "msg": str(tb)[:200]})

        self._send({
            "status": "ok",
            "total": tests_run,
            "passed": passed,
            "failed": len(result.failures),
            "errors": len(result.errors),
            "details": details,
            "time": f"{time.time()-t:.2f}s",
        })

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
