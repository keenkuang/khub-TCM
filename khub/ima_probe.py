"""IMA API 频率限制探测脚本。

三阶段探测策略：
  Phase 1 — 爆发测试（30 发，间隔 0.5s）: 找每分钟请求数阈值
  Phase 2 — 精细追踪（120 发，间隔 60s）: 找恢复时间 / 小时配额
  Phase 3 — 长期跟踪（每 15min）: 找日配额重置时间

记录到 JSONL 日志，每行一个探测结果。
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

BASE = "https://ima.qq.com/openapi/wiki/v1"
NOTE_BASE = "https://ima.qq.com/openapi/note/v1"
LOG_FILE = os.path.expanduser("~/.khub/ima_probe.jsonl")
PROBE_COUNTER = 0  # 全局累计请求计数


def _probe(endpoint: str = "search_knowledge_base") -> dict:
    """执行一次 API 探测，返回结果 dict。"""
    global PROBE_COUNTER
    PROBE_COUNTER += 1

    cid = os.environ.get("IMA_CLIENT_ID", "")
    akey = os.environ.get("IMA_API_KEY", "")
    if not cid or not akey:
        return {"error": "no credentials", "ok": False, "probe_n": PROBE_COUNTER,
                "endpoint": endpoint, "http": 0, "code": -99, "msg": "",
                "elapsed": 0}

    if endpoint in ("list_notebook", "list_note", "search_note"):
        url = f"{NOTE_BASE}/{endpoint}"
    else:
        url = f"{BASE}/{endpoint}"

    body = json.dumps({"query": "", "cursor": "", "limit": 1}).encode()

    # 不同端点用不同 body
    if endpoint == "list_notebook":
        body = json.dumps({"cursor": "0", "limit": 1}).encode()
    elif endpoint == "list_note":
        body = json.dumps({"folder_id": "", "cursor": "", "limit": 1}).encode()

    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("ima-openapi-clientid", cid)
    req.add_header("ima-openapi-apikey", akey)

    t0 = time.time()
    http_status = 0
    resp_code = -1
    resp_msg = ""
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            elapsed = round(time.time() - t0, 3)
            obj = json.loads(resp.read().decode())
            resp_code = obj.get("code", -1)
            resp_msg = obj.get("msg", "")
            http_status = resp.status
    except urllib.error.HTTPError as e:
        elapsed = round(time.time() - t0, 3)
        http_status = e.code
        resp_msg = str(e)
    except Exception as e:
        elapsed = round(time.time() - t0, 3)
        resp_msg = str(e)

    return {
        "ok": http_status == 200 and resp_code == 0,
        "endpoint": endpoint,
        "http": http_status,
        "code": resp_code,
        "msg": resp_msg[:80],
        "elapsed": round(elapsed, 3),
        "probe_n": PROBE_COUNTER,
    }


def _log(result: dict, log_path: str):
    """追加结果到日志（用 ts_local 做时间戳）。"""
    result["ts"] = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
    result["ts_local"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    result["tz"] = time.tzname[0] if hasattr(time, 'tzname') else ""

    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(result, ensure_ascii=False) + "\n")

    status = "OK" if result["ok"] else f"LIMIT({result.get('code','')})"
    print(f"  [#{result['probe_n']:>4}] {result['ts_local']}  {status:12s}  "
          f"{result['endpoint']:25s}  http={result.get('http','')}  "
          f"code={result.get('code','')}  {result.get('msg','')[:40]}  "
          f"{result.get('elapsed','')}s")


def run_burst(count: int = 30, interval: float = 0.5, log_path: str = LOG_FILE):
    """Phase 1: 爆发测试。连续发 count 次请求，间隔 interval 秒。"""
    print(f"[Phase 1] 爆发测试: {count} 发, 间隔 {interval}s")
    for i in range(count):
        r = _probe("search_knowledge_base")
        _log(r, log_path)
        # 触顶后休息久点再继续
        if not r["ok"] and r.get("code") in (200001, 220021):
            print(f"    ⚠️ 触顶! 等待 30s 后继续…")
            time.sleep(30)
        time.sleep(interval)


def run_fine(duration: int = 7200, interval: int = 60, log_path: str = LOG_FILE):
    """Phase 2: 精细追踪。每 interval 秒一次，持续 duration 秒。
    前 1/3 用知识库 API，中间 1/3 用笔记 API，后 1/3 轮换。"""
    n = duration // interval
    print(f"[Phase 2] 精细追踪: {n} 次, 间隔 {interval}s")
    endpoints = []
    for i in range(1, n + 1):
        if i <= n // 3:
            ep = "search_knowledge_base"
        elif i <= n * 2 // 3:
            ep = "list_notebook"
        else:
            ep = "search_knowledge_base" if i % 2 == 0 else "list_notebook"
        endpoints.append(ep)

    for ep in endpoints:
        r = _probe(ep)
        _log(r, log_path)
        time.sleep(interval)


def run_longterm(interval: int = 900, log_path: str = LOG_FILE):
    """Phase 3: 长期跟踪。每 interval 秒一次。"""
    print(f"[Phase 3] 长期跟踪: 间隔 {interval}s")
    while True:
        r = _probe("search_knowledge_base")
        _log(r, log_path)
        time.sleep(interval)


def probe_full(log_path: str = LOG_FILE):
    """运行完整三阶段探测（非阻塞模式）。"""
    run_burst(count=30, interval=0.5, log_path=log_path)
    run_fine(duration=3600, interval=30, log_path=log_path)
    run_longterm(interval=300, log_path=log_path)


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "full"
    if mode == "burst":
        run_burst()
    elif mode == "fine":
        run_fine()
    elif mode == "long":
        run_longterm()
    elif mode == "once":
        import khub.cli as _
    else:
        probe_full()
