import { useState, useEffect } from "react";
import "./App.css";

async function api(path: string, method = "GET", body?: unknown) {
  const r = await fetch(path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  return r.json();
}

function App() {
  const [tab, setTab] = useState("characters");
  const [chars, setChars] = useState<any[]>([]);
  useEffect(() => {
    api("/api/status").then(console.log);
    api("/api/characters").then((d) => setChars(Array.isArray(d) ? d : []));
  }, []);

  return (
    <div className="app">
      <header>
        <h1>Echo_Bot</h1>
      </header>
      <nav>
        {["characters", "tests", "settings"].map((t) => (
          <button key={t} className={tab === t ? "active" : ""} onClick={() => setTab(t)}>
            {t === "characters" ? "角色管理" : t === "tests" ? "功能测试" : "系统设置"}
          </button>
        ))}
      </nav>
      <main>
        {tab === "characters" && <Chars chars={chars} onRefresh={() => api("/api/characters").then((d) => setChars(Array.isArray(d) ? d : []))} />}
        {tab === "tests" && <Tests chars={chars} />}
        {tab === "settings" && <Settings />}
      </main>
    </div>
  );
}

function Chars({ chars, onRefresh }: { chars: any[]; onRefresh: () => void }) {
  const [editing, setEditing] = useState<any>(null);
  const [name, setName] = useState("");
  const [source, setSource] = useState("");
  const [traits, setTraits] = useState("");

  function open(c?: any) {
    setName(c?.name || "");
    setSource(c?.source || "");
    setTraits((c?.traits || []).join("、"));
    setEditing(c || {});
  }

  async function save() {
    if (!name) return alert("角色名不能为空");
    await api("/api/characters", "POST", { name, source, traits: traits.split(/[,，、]/).map((s: string) => s.trim()).filter(Boolean) });
    setEditing(null);
    onRefresh();
  }

  async function del(id: string) {
    if (!confirm("确认删除？")) return;
    await api("/api/characters/" + id, "DELETE");
    onRefresh();
  }

  return (
    <div className="card">
      <div style={{ display: "flex", justifyContent: "space-between" }}>
        <h2>角色列表</h2>
        <button className="btn primary" onClick={() => open()}>+ 添加</button>
      </div>
      {chars.map((c: any) => (
        <div key={c.id} className="row">
          <div><b>{c.name}</b> {c.source && <span className="dim">{c.source}</span>}<div className="dim">{(c.traits || []).slice(0, 4).join("、")}</div></div>
          <div><button className="btn" onClick={() => open(c)}>编辑</button><button className="btn danger" onClick={() => del(c.id)}>删除</button></div>
        </div>
      ))}
      {editing && (
        <div className="modal" onClick={() => setEditing(null)}>
          <div className="modal-c" onClick={(e) => e.stopPropagation()}>
            <h3>{editing.id ? "编辑" : "添加"}角色</h3>
            <label>角色名 <input value={name} onChange={(e) => setName(e.target.value)} /></label>
            <label>出处 <input value={source} onChange={(e) => setSource(e.target.value)} /></label>
            <label>标签 <input value={traits} onChange={(e) => setTraits(e.target.value)} placeholder="逗号分隔" /></label>
            <div style={{ display: "flex", gap: 8, justifyContent: "flex-end", marginTop: 12 }}>
              <button className="btn" onClick={() => setEditing(null)}>取消</button>
              <button className="btn primary" onClick={save}>保存</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function Tests({ chars }: { chars: any[] }) {
  const [charId, setCharId] = useState("");
  const [query, setQuery] = useState("");
  const [result, setResult] = useState("");

  async function run(action: string) {
    setResult("运行中...");
    const r = await api("/api/test/" + action, "POST", {
      char_id: charId, message: query, text: query, query: query,
    });
    if (action === "prompt") setResult(r.prompt || r.error || "");
    else if (action === "split") setResult((r.parts || []).map((p: string, i: number) => `[${i}] ${p}`).join("\n"));
    else if (action === "retriever") setResult((r.results || []).map((v: any) => `[${v.score.toFixed(2)}] ${v.line}`).join("\n") || r.error || "无结果");
    else if (action === "run_all") setResult(`通过: ${r.passed}/${r.total}  失败: ${r.failed}\n${(r.details || []).map((d: any) => `[!] ${d.test}`).join("\n")}`);
    else setResult(JSON.stringify(r, null, 2));
  }

  return (
    <div className="card">
      <h2>功能测试</h2>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 12 }}>
        <select value={charId} onChange={(e) => setCharId(e.target.value)}>
          <option value="">选择角色</option>
          {chars.map((c: any) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
        <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="输入..." style={{ flex: 1 }} />
      </div>
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 12 }}>
        {["prompt", "retriever", "split", "memory", "scheduler"].map((a) => (
          <button key={a} className="btn primary" onClick={() => run(a)}>{a}</button>
        ))}
        <button className="btn" onClick={() => run("run_all")}>全量</button>
      </div>
      <pre className="result">{result}</pre>
    </div>
  );
}

function Settings() {
  const [info, setInfo] = useState<any>(null);
  const [msg, setMsg] = useState("");
  useEffect(() => { api("/api/system").then(setInfo); }, []);
  return (
    <>
      <div className="card">
        <h2>系统信息</h2>
        <pre>{JSON.stringify(info, null, 2)}</pre>
      </div>
      <div className="card">
        <h2>记忆管理</h2>
        <button className="btn primary" onClick={async () => { const r = await api("/api/memory/compress", "POST", {}); setMsg(r.msg || "完成"); }}>压缩记忆</button>
        {msg && <p>{msg}</p>}
      </div>
    </>
  );
}

export default App;
