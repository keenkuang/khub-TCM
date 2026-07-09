"""IMA API 多端点频率限制探测。

以 0.5s 间隔依次轮询不同权重的端点，画出完整配额地图：
  轻量: search_knowledge_base
  中量: get_knowledge_list, list_notebook
  重量: get_media_info（需真实 media_id，由外部注入）
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

BURST_INTERVAL = 0.5     # 爆发间隔（秒）
RECOVERY_WAIT = 90       # 触顶后等待时间（秒）

# 不同权重端点的探测 URL / body 模板
ENDPOINTS = [
    ("list_notebook", NOTE_BASE, {"cursor": "0", "limit": 1}, "中量"),
    ("get_knowledge_list", BASE, {"cursor": "", "limit": 1, "knowledge_base_id": "__PLACEHOLDER__", "folder_id": ""}, "中量"),
]


def _probe() -> dict:
    """轮询下一个端点执行一次探测，返回结果。"""
    cid = os.environ.get("IMA_CLIENT_ID", "")
    akey = os.environ.get("IMA_API_KEY", "")
    if not cid or not akey:
        return {"ok": False, "http": 0, "code": -99, "msg": "no creds",
                "endpoint": "", "weight": "", "elapsed": 0}

    # 轮询选择下一个端点（按索引循环）
    _probe.idx = getattr(_probe, "idx", -1) + 1
    ep_name, ep_base, ep_body, ep_weight = ENDPOINTS[_probe.idx % len(ENDPOINTS)]
    url = f"{ep_base}/{ep_name}"
    body = json.dumps(ep_body).encode()

    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("ima-openapi-clientid", cid)
    req.add_header("ima-openapi-apikey", akey)

    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            obj = json.loads(resp.read().decode())
            result = {"ok": obj.get("code") == 0, "http": resp.status,
                      "code": obj.get("code", -1), "msg": obj.get("msg", "")[:80]}
    except urllib.error.HTTPError as e:
        result = {"ok": False, "http": e.code, "code": -1, "msg": str(e)[:80]}
    except Exception as e:
        result = {"ok": False, "http": 0, "code": -2, "msg": str(e)[:80]}

    result["endpoint"] = ep_name
    result["weight"] = ep_weight
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


def run_multi_endpoint(log_path: str = LOG_FILE):
    """多端点轮询探测。"""
    total = 0
    burst_id = 0
    burst_count = 0
    burst_start = time.time()

    print(f"[ima_probe] 多端点探测启动 — 轮询 {len(ENDPOINTS)} 个端点, 爆发间隔 {BURST_INTERVAL}s")
    cols = f"{'#':>5} {'时间':16s} {'结果':8s} {'端点':28s} {'权重':6s} {'code':>6s}  {'耗时'}"
    print(cols)
    print("-" * len(cols))

    while True:
        r = _probe()
        ts_local = time.strftime("%m-%d %H:%M:%S", time.localtime())
        total += 1
        burst_count += 1

        if r["ok"]:
            if total % 10 == 0 or burst_count == 1:
                print(f"  {total:>5} {ts_local}  {'OK':>8s}  {r['endpoint']:28s}  "
                      f"{r['weight']:6s}  {r['code']:>6d}  {r['elapsed']}s")
            _log(r, log_path)
            time.sleep(BURST_INTERVAL)
            continue

        # 被限
        burst_dur = time.time() - burst_start
        print(f"⚠ {total:>5} {ts_local}  {'LIMIT':>8s}  {r['endpoint']:28s}  "
              f"{r['weight']:6s}  {r['code']:>6d}  {r['elapsed']}s  {r['msg'][:40]}")
        _log(r, log_path)

        burst_id += 1
        summary = {
            "type": "burst_summary",
            "burst_id": burst_id,
            "burst_size": burst_count,
            "burst_duration": round(burst_dur, 1),
            "total_requests": total,
            "limit_code": r["code"],
            "limit_endpoint": r["endpoint"],
            "limit_weight": r["weight"],
            "limit_msg": r["msg"][:80],
            "ts_local": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
        }
        _log(summary, log_path)

        wait = RECOVERY_WAIT
        print(f"    ⏳ 等待 {wait}s 恢复...")
        time.sleep(wait)

        burst_start = time.time()
        burst_count = 0


if __name__ == "__main__":
    run_multi_endpoint()
