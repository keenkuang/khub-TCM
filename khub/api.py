import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional
from urllib.parse import parse_qs, urlparse, unquote

from . import __version__
from .db import Store
from .ingest import ingest_ebook, register_ebook
from .log import get_logger
from .models import CanonicalDoc
from .storage import ManagedLibrary


class App:
    """薄 REST 层：直接复用核心库 API，不重写业务逻辑。"""

    def __init__(self, store: Store, library: ManagedLibrary):
        self.store = store
        self.library = library
        self._started = time.time()

    def dispatch(self, method: str, raw_path: str, body: Optional[dict] = None,
                 auth_header: str = ""):
        # 写操作鉴权（可选，由 KHUB_API_TOKEN 环境变量控制）
        if method in ("POST", "PUT", "DELETE"):
            token = os.environ.get("KHUB_API_TOKEN")
            if token:
                if auth_header != f"Bearer {token}":
                    return 401, {"error": "unauthorized"}
        parsed = urlparse(raw_path)
        path = parsed.path
        qs = parse_qs(parsed.query)
        body = body or {}

        # ---- Static file serving (web/ directory, path traversal protected) ----
        if method == "GET" and path.startswith("/web/"):
            filename = path[len("/web/"):]
            web_dir = os.path.realpath(os.path.join(os.path.dirname(__file__), "web"))
            filepath = os.path.realpath(os.path.join(web_dir, filename))
            if not filepath.startswith(web_dir + os.sep):
                return 404, {"error": "bad path"}
            if not os.path.isfile(filepath):
                return 404, {"error": "not found"}
            with open(filepath, "rb") as f:
                return 200, f.read(), "application/octet-stream"

        if method == "GET" and path == "/health":
            uptime = round(time.time() - self._started, 1) if self._started else 0
            return 200, {"status": "ok", "version": __version__,
                         "documents": self.store.conn.execute(
                             "SELECT count(*) FROM documents").fetchone()[0],
                         "uptime_sec": uptime}

        if method == "GET" and path == "/stats":
            cur = self.store.conn
            total = cur.execute("SELECT count(*) FROM documents").fetchone()[0]
            sources = {}
            for row in cur.execute("SELECT source_ids FROM documents").fetchall():
                ids = row["source_ids"] or "[]"
                for src in ("obsidian", "ima", "imanote", "quip", "kzocr", "library"):
                    if f'"{src}"' in ids:
                        sources[src] = sources.get(src, 0) + 1
                        break
            today = time.strftime("%Y-%m-%d")
            today_count = cur.execute(
                "SELECT count(*) FROM documents WHERE updated_at >= ?",
                (today,)).fetchone()[0]
            recent = cur.execute(
                "SELECT canonical_id, title, updated_at FROM documents "
                "ORDER BY updated_at DESC LIMIT 5").fetchall()
            return 200, {
                "total": total,
                "sources": sources,
                "today": today_count,
                "recent": [{"id": r["canonical_id"], "title": r["title"], "at": r["updated_at"]}
                           for r in recent],
            }

        if method == "GET" and path == "/ebooks":
            return 200, self.store.list_ebooks()

        if method == "POST" and path == "/ebooks/register":
            cid = register_ebook(self.store, self.library, body["path"],
                                 move=bool(body.get("move")))
            return 201, {"canonical_id": cid}

        if method == "POST" and path.endswith("/ingest"):
            prefix = "/ebooks/"
            if path.startswith(prefix) and path.endswith("/ingest"):
                cid = path[len(prefix):-len("/ingest")]
                vid = ingest_ebook(self.store, cid)
                return 200, {"canonical_id": cid, "version_id": vid}
            return 404, {"error": "not found"}

        if method == "GET" and path == "/search":
            q = qs.get("q", [""])[0]
            page = int(qs.get("page", ["0"])[0])
            per = int(qs.get("per", ["50"])[0])
            source = qs.get("source", [""])[0]
            hits, total = self.store.search(q, page=page, per_page=per, source=source)
            return 200, {"hits": [{"doc_id": d, "title": t, "snippet": s}
                                   for d, t, s in hits],
                         "total": total, "page": page, "per_page": per}

        if method == "GET" and path == "/documents":
            rows = self.store.conn.execute(
                "SELECT canonical_id, title, updated_at, source_ids FROM documents "
                "ORDER BY updated_at DESC").fetchall()
            return 200, [dict(r) for r in rows]

        if method == "GET" and path.startswith("/documents/") and len(path) > len("/documents/"):
            cid = unquote(path[len("/documents/"):])
            doc = self.store.get_document(cid)
            if doc is None:
                return 404, {"error": "not found"}
            vers = self.store.get_versions(cid)
            content = vers[-1]["content"] if vers else ""
            return 200, {
                "canonical_id": doc["canonical_id"],
                "title": doc["title"],
                "content": content[:100000],  # 截断防超大文本
                "version_count": len(vers),
                "source_ids": doc["source_ids"],
                "created_at": doc["created_at"],
                "updated_at": doc["updated_at"],
                "format": vers[-1]["format"] if (vers and "format" in vers[-1]) else "plain",
            }

        if method == "GET" and path == "/conflicts":
            rows = self.store.conn.execute(
                "SELECT canonical_id, title FROM documents WHERE conflict=1").fetchall()
            return 200, [dict(r) for r in rows]

        if method == "GET" and path == "/semantic":
            from .retrieval import Retriever
            q = qs.get("q", [""])[0]
            k = int(qs.get("k", ["5"])[0] or 5)
            hits = Retriever(self.store).search_similar(q, k=k)
            return 200, [{"doc_id": d, "score": round(s, 4)} for d, s in hits]

        if method == "GET" and path == "/":
            return 200, self._html_page(), "text/html; charset=utf-8"

        # ---- OCR / KZOCR 文档入库（直接收内容，不依赖原始文件） ----
        if method == "POST" and path == "/documents":
            if not body.get("title") or not body.get("content"):
                return 400, {"error": "title 与 content 必填"}
            doc = CanonicalDoc(
                canonical_id=body.get("source_id") or f"kzocr-{int(time.time()*1000)}",
                title=body["title"],
                content=body["content"],
                source=body.get("source", "KZOCR"),
                source_id=body.get("source_id") or "",
                origin="kzocr",
                format=body.get("format", "markdown"),
                updated_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
                note=json.dumps(body.get("metadata") or {}, ensure_ascii=False),
                doc_type=body.get("doc_type", "raw"),
            )
            version_id = self.store.store_document(doc)
            try:
                from .retrieval import Retriever
                Retriever(self.store).index_ebook(doc.canonical_id)
            except Exception:  # 向量化失败不影响入库
                pass
            return 201, {"status": "ok", "doc_id": doc.canonical_id,
                         "version_id": version_id, "message": "document ingested"}

        # ---- Exam subsystem ----
        if method == "POST" and path == "/exam/questions":
            from .exam.models import Question
            from .exam.store import add_question
            q = Question(kind=body.get("kind", "mcq"), stem=body.get("stem", ""),
                         options=body.get("options", []), answer=body.get("answer", ""),
                         explanation=body.get("explanation", ""),
                         source_doc=body.get("source_doc", ""))
            qid = add_question(self.store, q)
            return 201, {"id": qid}

        if method == "GET" and path == "/exam/questions":
            from .exam.store import list_questions
            kind = qs.get("kind", [None])[0]
            return 200, [vars(q) for q in list_questions(self.store, kind)]

        if method == "POST" and path == "/exam/generate":
            from .exam.generator import generate
            topic = body.get("topic", "")
            source_doc = body.get("source_doc", "")
            q = generate(topic, source_doc=source_doc)
            return 200, vars(q)

        # ---- Clinical subsystem ----
        if method == "POST" and path == "/clinical/patients":
            from .clinical.patients import add_patient
            pid = add_patient(self.store, body["id"], body["name"],
                              gender=body.get("gender", ""), born=body.get("born", ""))
            return 201, {"id": pid}

        if method == "GET" and path == "/clinical/patients":
            from .clinical.patients import list_patients
            return 200, list_patients(self.store)

        if method == "POST" and path == "/clinical/records":
            from .clinical.records import add_record
            rid = add_record(self.store, body["patient_id"],
                             diagnosis=body.get("diagnosis", ""),
                             prescription=body.get("prescription", ""),
                             note=body.get("note", ""))
            return 201, {"id": rid}

        if method == "POST" and path == "/clinical/consultations":
            from .clinical.consultations import add_consultation
            cid = add_consultation(self.store, body["patient_id"],
                                   chief_complaint=body.get("chief_complaint", ""),
                                   tongue_pulse=body.get("tongue_pulse", ""),
                                   differentiation=body.get("differentiation", ""),
                                   plan=body.get("plan", ""))
            return 201, {"id": cid}

        if method == "POST" and path.startswith("/clinical/twin/") and path.endswith("/summarize"):
            pid = path[len("/clinical/twin/"):-len("/summarize")]
            from .clinical.records import init as init_records
            from .clinical.consultations import init as init_consultations
            from .clinical.twin import build_summary
            init_records(self.store)
            init_consultations(self.store)
            text = build_summary(self.store, pid)
            return 200, {"patient_id": pid, "summary": text}

        # ---- Ops subsystem ----
        if method == "POST" and path == "/ops/schedules":
            from .ops.store import add_schedule
            sid = add_schedule(self.store, body["date"], body["doctor"], body["slot"])
            return 201, {"id": sid}

        if method == "POST" and path == "/ops/appointments":
            from .ops.store import book_appointment
            aid = book_appointment(self.store, body["patient_id"], body["date"], body["doctor"])
            return 201, {"id": aid}

        if method == "POST" and path == "/ops/visits":
            from .ops.store import checkin_visit
            vid = checkin_visit(self.store, body["appointment_id"], body["patient_id"],
                                note=body.get("note", ""))
            return 201, {"id": vid}

        if method == "GET" and path == "/ops/appointments":
            from .ops.store import list_appointments
            date = qs.get("date", [None])[0]
            return 200, list_appointments(self.store, date)

        return 404, {"error": "not found"}

    @staticmethod
    def _html_page():
        return """<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>kHUB</title>
<style>
 body{font-family:system-ui,"PingFang SC","Microsoft YaHei",sans-serif;margin:0;background:#f6f7f9;color:#222}
 header{background:#1f2937;color:#fff;padding:12px 20px;font-weight:600}
 .wrap{max-width:920px;margin:20px auto;padding:0 16px}
 .bar{display:flex;gap:8px;margin-bottom:14px;flex-wrap:wrap}
 input[type=text]{flex:1;min-width:200px;padding:9px 12px;border:1px solid #ccd;border-radius:8px;font-size:15px}
 button{padding:9px 14px;border:0;border-radius:8px;background:#2563eb;color:#fff;cursor:pointer;font-size:14px}
 button.ghost{background:#e5e7eb;color:#333}
 .card{background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:12px 14px;margin-bottom:10px}
 .card h3{margin:0 0 4px;font-size:16px}
 .snip{color:#555;font-size:14px;line-height:1.5}
 .meta{color:#999;font-size:12px;margin-top:4px}
 .tag{display:inline-block;background:#fee2e2;color:#b91c1c;border-radius:6px;padding:1px 7px;font-size:12px}
 h2{font-size:15px;color:#555;margin:18px 0 8px}
</style></head>
<body>
<header>kHUB · 个人知识中枢</header>
<div class="wrap">
  <div id="stats" style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:14px"></div>
  <div class="bar">
    <input id="q" type="text" placeholder="全文检索（中文子串，如 桂枝汤 / 麻黄）">
    <button onclick="search()">检索</button>
    <button class="ghost" onclick="semantic()">语义</button>
    <button class="ghost" onclick="loadAll()">全部文档</button>
    <button class="ghost" onclick="loadConflicts()">冲突</button>
    <select id="sourceFilter" style="padding:6px 8px;border:1px solid #ccd;border-radius:6px;font-size:13px">
      <option value="">所有来源</option>
      <option value="obsidian">秘方</option>
      <option value="ima">IMA</option>
      <option value="imanote">IMA笔记</option>
      <option value="quip">Quip</option>
      <option value="kzocr">KZOCR</option>
    </select>
  </div>
  <div id="results"></div>
</div>
<script>
const box=document.getElementById('results');
let currentPage=0;const PER_PAGE=20;
function card(d, clickable=true, highlightTerm=''){
  const el=document.createElement('div');el.className='card';
  el.innerHTML=`<h3>${highlight(d.title||d.doc_id||'', highlightTerm)}</h3>`+
    (d.snippet?`<div class="snip">${highlight(d.snippet, highlightTerm)}</div>`:'')+
    `<div class="meta">${esc(d.doc_id||'')}${d.updated_at?' · '+esc(d.updated_at):''}`+
    `${d.conflict?` <span class="tag">冲突</span>`:''}</div>`;
  if(clickable && d.doc_id){
    el.style.cursor='pointer';
    el.onclick=()=>loadDoc(d.doc_id, d.title);
  }
  return el;
}
function esc(s){return (s||'').replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));}
function highlight(s,term){
  s=esc(s);if(!term)return s;
  const re=new RegExp(esc(term).replace(/[.*+?^${}()|[\\]\\\\]/g,'\\$&'),'gi');
  return s.replace(re,m=>'<mark>'+m+'</mark>');
}
async function loadDoc(id, title){
  box.innerHTML=`<h2>${esc(title||id)}</h2><p class="meta">加载中...</p>`;
  try{
    const r=await fetch('/documents/'+encodeURIComponent(id)).then(x=>x.json());
    if(r.error){box.innerHTML=`<p class="meta">${esc(r.error)}</p>`;return;}
    const backLink = '<p style="margin-bottom:8px"><a href="#" onclick="loadAll();return false">← 返回列表</a></p>';
    box.innerHTML=backLink;
    box.innerHTML+=`<h2>${esc(r.title||id)}</h2><p class="meta">${esc(r.canonical_id)} · ${r.version_count} 版本 · ${r.updated_at||''} · 格式: ${esc(r.format||'')}</p>`;
    let contentDiv;
    if(r.format === 'html'){
      const safe = (r.content||'').replace(/<script[\\s\\S]*?<\\/script>/gi,'');
      contentDiv = `<div style="line-height:1.7;padding:12px;border-radius:8px;margin-top:8px;overflow-x:auto">${safe}</div>`;
    } else {
      contentDiv = `<div style="white-space:pre-wrap;font-size:14px;line-height:1.7;background:#fafafa;padding:12px;border-radius:8px;margin-top:8px;overflow-x:auto">${esc(r.content)}</div>`;
    }
    box.innerHTML += contentDiv + backLink;
  }catch(e){box.innerHTML=`<p class="meta">加载失败: ${esc(e.message)}</p>`;}
}
async function search(){
  currentPage=0;
  const q=document.getElementById('q').value.trim();if(!q)return;
  box.innerHTML='';
  const source=document.getElementById('sourceFilter').value;
  const r=await fetch(`/search?q=${encodeURIComponent(q)}&page=${currentPage}&per=${PER_PAGE}&source=${encodeURIComponent(source)}`).then(x=>x.json());
  if(!r.total){box.innerHTML='<p class="meta">无结果</p>';return;}
  const from = currentPage * PER_PAGE + 1;
  const to = Math.min((currentPage+1)*PER_PAGE, r.total);
  const h=document.createElement('h2');h.textContent=`命中 ${r.total} 篇（第${from}-${to}篇）`;box.appendChild(h);
  r.hits.forEach(d=>box.appendChild(card(d, true, q)));
  if((currentPage + 1) * PER_PAGE < r.total){
    const btn=document.createElement('button');btn.textContent='下一页 →';btn.style.margin='10px auto';btn.style.display='block';
    btn.onclick=()=>{currentPage++;search();};
    box.appendChild(btn);
  }
}
async function semantic(){
  const q=document.getElementById('q').value.trim();if(!q)return;
  box.innerHTML='';
  const h=document.createElement('h2');h.textContent='语义检索（向量 / ANN）';box.appendChild(h);
  const r=await fetch('/semantic?q='+encodeURIComponent(q)).then(x=>x.json());
  if(!r.length){box.innerHTML+='<p class="meta">无结果</p>';return;}
  const docs=await fetch('/documents').then(x=>x.json());
  const titles={};docs.forEach(d=>titles[d.canonical_id]=d.title);
  r.forEach(d=>{const el=document.createElement('div');el.className='card';
    el.innerHTML=`<h3>${esc(titles[d.doc_id]||d.doc_id)}</h3><div class="meta">${esc(d.doc_id)} · 相似度 ${d.score}</div>`;
    el.style.cursor='pointer';el.onclick=()=>loadDoc(d.doc_id, titles[d.doc_id]||d.doc_id);box.appendChild(el);});
}
async function loadAll(){
  box.innerHTML='';const h=document.createElement('h2');h.textContent='全部文档';
  box.appendChild(h);
  const r=await fetch('/documents').then(x=>x.json());
  if(!r.length){box.innerHTML+='<p class="meta">暂无文档</p>';return;}
  r.forEach(d=>box.appendChild(card({doc_id:d.canonical_id,title:d.title,updated_at:d.updated_at})));
}
async function loadConflicts(){
  box.innerHTML='';const h=document.createElement('h2');h.textContent='冲突文档';
  box.appendChild(h);
  const r=await fetch('/conflicts').then(x=>x.json());
  if(!r.length){box.innerHTML+='<p class="meta">无冲突</p>';return;}
  r.forEach(d=>box.appendChild(card(d)));
}
async function loadStats(){
  const s=document.getElementById('stats');
  try{
    const r=await fetch('/stats').then(x=>x.json());
    let html=`<div class="stat-card" style="background:#e8f5e9;padding:8px 14px;border-radius:8px;text-align:center;min-width:70px"><div style="font-size:20px;font-weight:700">${r.total}</div><div style="font-size:11px;color:#555">总计</div></div>`;
    const srcMap={'obsidian':'秘方','ima':'IMA','imanote':'IMA笔记','quip':'Quip','library':'电子书'};
    for(const [k,v] of Object.entries(srcMap)){
      const cnt=r.sources[k]||0;
      if(cnt>0) html+=`<div class="stat-card" style="background:#e3f2fd;padding:8px 14px;border-radius:8px;text-align:center;min-width:60px"><div style="font-size:16px;font-weight:700">${cnt}</div><div style="font-size:11px;color:#555">${v}</div></div>`;
    }
    html+=`<div class="stat-card" style="background:#fff3e0;padding:8px 14px;border-radius:8px;text-align:center;min-width:60px"><div style="font-size:16px;font-weight:700">${r.today}</div><div style="font-size:11px;color:#555">今日</div></div>`;
    s.innerHTML=html;
  }catch(e){s.innerHTML='';}
}
loadStats();
document.getElementById('q').addEventListener('keydown',e=>{if(e.key==='Enter')search();});
loadAll();
</script>
</body></html>"""


def make_handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, code, obj, ctype="application/json; charset=utf-8"):
            if ctype.startswith("application/json"):
                data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            else:
                data = obj.encode("utf-8") if isinstance(obj, str) else obj
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            try:
                res = app.dispatch("GET", self.path,
                                   auth_header=self.headers.get("Authorization", ""))
                if len(res) == 3:
                    code, obj, ctype = res
                else:
                    code, obj, ctype = res[0], res[1], "application/json; charset=utf-8"
            except Exception as e:  # noqa: BLE001
                return self._send(500, {"error": str(e)})
            self._send(code, obj, ctype)

        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0) or 0)
            raw = self.rfile.read(length) if length else b"{}"
            try:
                body = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                return self._send(400, {"error": "bad json"})
            try:
                res = app.dispatch("POST", self.path, body,
                                   auth_header=self.headers.get("Authorization", ""))
                if len(res) == 3:
                    code, obj, ctype = res
                else:
                    code, obj, ctype = res[0], res[1], "application/json; charset=utf-8"
            except Exception as e:  # noqa: BLE001
                return self._send(500, {"error": str(e)})
            self._send(code, obj, ctype)

        def do_PUT(self):
            length = int(self.headers.get("Content-Length", 0) or 0)
            raw = self.rfile.read(length) if length else b"{}"
            try:
                body = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                return self._send(400, {"error": "bad json"})
            try:
                res = app.dispatch("PUT", self.path, body,
                                   auth_header=self.headers.get("Authorization", ""))
                if len(res) == 3:
                    code, obj, ctype = res
                else:
                    code, obj, ctype = res[0], res[1], "application/json; charset=utf-8"
            except Exception as e:  # noqa: BLE001
                return self._send(500, {"error": str(e)})
            self._send(code, obj, ctype)

        def do_DELETE(self):
            length = int(self.headers.get("Content-Length", 0) or 0)
            raw = self.rfile.read(length) if length else b"{}"
            try:
                body = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                return self._send(400, {"error": "bad json"})
            try:
                res = app.dispatch("DELETE", self.path, body,
                                   auth_header=self.headers.get("Authorization", ""))
                if len(res) == 3:
                    code, obj, ctype = res
                else:
                    code, obj, ctype = res[0], res[1], "application/json; charset=utf-8"
            except Exception as e:  # noqa: BLE001
                return self._send(500, {"error": str(e)})
            self._send(code, obj, ctype)

        def log_message(self, *args):
            pass

    return Handler


def serve(store: Store, library: ManagedLibrary, host: str = "127.0.0.1", port: int = 8000):
    app = App(store, library)
    httpd = ThreadingHTTPServer((host, port), make_handler(app))
    import signal

    def _stop(*a):
        print("\n收到停止信号，正在关闭...")
        httpd.shutdown()

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    print(f"kHUB API → http://{host}:{port}  (pid={os.getpid()})")
    httpd.serve_forever()
