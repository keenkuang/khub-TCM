"""IMA API 频率限制探测 — 科学探测法。

持续以 0.5s 间隔连续发请求，直到被限速：
  - 记录本次爆发请求数、错误码、恢复时间
  - 等 30s 恢复后续爆发
循环，完整描绘配额阶梯。
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

# 探测参数
BURST_INTERVAL = 0.3   # 爆发间隔（秒）
RECOVERY_WAIT = 120     # 触顶后等待秒数（完全恢复需要 ~90s）


def _probe(endpoint: str) -> dict:
    """执行一次 API 探测，返回结构化结果。"""
    cid = os.environ.get("IMA_CLIENT_ID", "")
    akey = os.environ.get("IMA_API_KEY", "")
    if not cid or not akey:
        return {"ok": False, "http": 0, "code": -99, "msg": "no credentials",
                "endpoint": endpoint, "elapsed": 0}

    if endpoint in ("list_notebook", "list_note", "search_note"):
        url = f"{NOTE_BASE}/{endpoint}"
    else:
        url = f"{BASE}/{endpoint}"

    if endpoint == "list_notebook":
        body = json.dumps({"cursor": "0", "limit": 1}).encode()
    elif endpoint == "list_note":
        body = json.dumps({"folder_id": "", "cursor": "", "limit": 1}).encode()
    else:
        body = json.dumps({"query": "", "cursor": "", "limit": 1}).encode()

    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("ima-openapi-clientid", cid)
    req.add_header("ima-openapi-apikey", akey)

    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            obj = json.loads(resp.read().decode())
            result = {
                "ok": obj.get("code") == 0,
                "http": resp.status,
                "code": obj.get("code", -1),
                "msg": obj.get("msg", "")[:80],
            }
    except urllib.error.HTTPError as e:
        result = {"ok": False, "http": e.code, "code": -1, "msg": str(e)[:80]}
    except Exception as e:
        result = {"ok": False, "http": 0, "code": -2, "msg": str(e)[:80]}

    result["endpoint"] = endpoint
    result["elapsed"] = round(time.time() - t0, 3)
    return result


def _log(result: dict, log_path: str):
    """追加结果到日志 JSONL。"""
    result["ts"] = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
    result["ts_local"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    result["tz"] = time.tzname[0] if hasattr(time, 'tzname') else ""

    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(result, ensure_ascii=False) + "\n")


def run_scientific(endpoint: str = "search_knowledge_base", log_path: str = LOG_FILE):
    """科学探测：持续爆发直到被限，恢复后继续。"""
    total_reqs = 0
    burst_id = 0
    burst_start = time.time()
    burst_count = 0

    print(f"[ima_probe] 科学探测启动 — endpoint={endpoint} 爆发间隔={BURST_INTERVAL}s")
    print(f"{'#'*5} {'时间':19s} {'状态':>8s} {'爆发':>6s} {'总计':>6s} {'code':>6s}  {'耗时'}  msg")
    print("-" * 80)

    while True:
        r = _probe(endpoint)
        ts_local = time.strftime("%m-%d %H:%M:%S", time.localtime())
        total_reqs += 1
        burst_count += 1

        if r["ok"]:
            # 成功：继续爆发
            if total_reqs % 10 == 0:
                print(f"  {ts_local}  {'OK':>8s}  {burst_count:>6d}  {total_reqs:>6d}  "
                      f"{r['code']:>6d}  {r['elapsed']}s")
            _log(r, log_path)
            time.sleep(BURST_INTERVAL)
            continue

        # 被限速了！
        burst_dur = time.time() - burst_start
        print(f"⚠ LIMIT  {ts_local}  {'LIMIT':>8s}  {burst_count:>6d}  {total_reqs:>6d}  "
              f"{r['code']:>6d}  {r['elapsed']}s  {r['msg'][:40]}")
        _log(r, log_path)

        # 记录爆发统计
        burst_id += 1
        summary = {
            "type": "burst_summary",
            "burst_id": burst_id,
            "burst_size": burst_count,
            "burst_duration": round(burst_dur, 1),
            "burst_rate": round(burst_count / max(burst_dur, 0.1), 1),
            "total_requests": total_reqs,
            "limit_code": r["code"],
            "limit_msg": r["msg"][:80],
            "ts_local": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
        }
        _log(summary, log_path)

        # 等 120s 完全恢复后继续
        wait = RECOVERY_WAIT
        last_limit = {"code": r["code"], "at": time.time()}

        print(f"    ⏳ 等待 {wait}s 恢复...")
        time.sleep(wait)

        # 恢复后重置爆发计数
        burst_start = time.time()
        burst_count = 0

        # 恢复后先测一次确认
        retry = _probe(endpoint)
        if retry["ok"]:
            print(f"    ✅ 已恢复，继续爆发")
            _log(retry, log_path)
            total_reqs += 1
        else:
            print(f"    ❌ 仍未恢复，继续等待...")


if __name__ == "__main__":
    endpoint = sys.argv[1] if len(sys.argv) > 1 else "search_knowledge_base"
    run_scientific(endpoint)
