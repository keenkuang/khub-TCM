"""IMA API 频率限制探测脚本。
每小时探测一次，记录配额状态，用于分析 IMA API 的限速规律（日配额/小时配额/请求间隔）。
记录到 JSONL 日志文件，每行一个探测结果。
"""
import json
import os
import time
import urllib.error
import urllib.request

BASE = "https://ima.qq.com/openapi/wiki/v1"
LOG_FILE = os.path.expanduser("~/.khub/ima_probe.jsonl")


def _probe():
    """执行一次轻量探测（search_knowledge_base limit=1），返回结果 dict。"""
    cid = os.environ.get("IMA_CLIENT_ID", "")
    akey = os.environ.get("IMA_API_KEY", "")
    if not cid or not akey:
        return {"error": "no credentials", "ok": False}

    url = f"{BASE}/search_knowledge_base"
    body = json.dumps({"query": "", "cursor": "", "limit": 1}).encode()
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("ima-openapi-clientid", cid)
    req.add_header("ima-openapi-apikey", akey)

    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            elapsed = round(time.time() - t0, 3)
            obj = json.loads(resp.read().decode())
            code = obj.get("code", -1)
            msg = obj.get("msg", "")
            return {
                "ok": code == 0,
                "http": resp.status,
                "code": code,
                "msg": msg,
                "elapsed": elapsed,
            }
    except urllib.error.HTTPError as e:
        elapsed = round(time.time() - t0, 3)
        return {
            "ok": False,
            "http": e.code,
            "code": -1,
            "msg": str(e),
            "elapsed": elapsed,
        }
    except Exception as e:
        elapsed = round(time.time() - t0, 3)
        return {
            "ok": False,
            "http": 0,
            "code": -2,
            "msg": str(e),
            "elapsed": elapsed,
        }


def probe_once(log_path: str = LOG_FILE):
    """执行一次探测，追加到日志文件。返回探测结果。"""
    result = _probe()
    result["ts"] = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
    result["ts_local"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    result["tz"] = time.tzname[0] if hasattr(time, 'tzname') else ""

    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(result, ensure_ascii=False) + "\n")

    return result


def probe_loop(interval: int = 3600, log_path: str = LOG_FILE):
    """持续探测循环。每 interval 秒执行一次。"""
    print(f"[ima_probe] 开始探测，间隔 {interval}s，日志: {log_path}")
    while True:
        r = probe_once(log_path)
        status = "OK" if r["ok"] else f"LIMIT({r.get('code','')})"
        print(f"  {r['ts_local']}  {status}  http={r.get('http','')}  "
              f"code={r.get('code','')}  {r.get('msg','')[:60]}  "
              f"elapsed={r.get('elapsed','')}s")
        time.sleep(interval)


if __name__ == "__main__":
    import sys
    interval = int(sys.argv[1]) if len(sys.argv) > 1 else 3600
    probe_loop(interval)
