"""多 Agent 集成——并行执行 + 投票 + 级联。"""
from __future__ import annotations
import json, threading
from typing import Any
from ..db import Store
from .store import get_agent
from .engine import run_with_llm


def run_parallel(store: Store, agent_ids: list[int], input_text: str = "",
                 current_user: dict | None = None) -> list[dict]:
    """并行执行多个 Agent，各自独立处理相同输入。"""
    results = []
    lock = threading.Lock()

    def _run(aid):
        agent = get_agent(store, aid)
        if not agent: return
        result = run_with_llm(store, aid, user_input=input_text, current_user=current_user)
        with lock:
            results.append({"agent_id": aid, "agent_name": agent["name"],
                            "output": result.get("reply", "")})

    threads = [threading.Thread(target=_run, args=(aid,)) for aid in agent_ids]
    for t in threads: t.start()
    for t in threads: t.join()
    return results


def vote(store: Store, agent_ids: list[int], input_text: str = "",
         current_user: dict | None = None) -> dict:
    """多个 Agent 投票：各自独立判断，统计多数意见。"""
    results = run_parallel(store, agent_ids, input_text, current_user)
    outputs = [r["output"] for r in results if r.get("output")]
    # 简单多数投票（相同或相似输出计数）
    from collections import Counter
    # 取每个输出前 50 字作为 key
    keys = [o[:50] for o in outputs if o]
    if not keys: return {"consensus": "无结果", "votes": {}}
    counter = Counter(keys)
    top = counter.most_common(1)[0]
    consensus_output = outputs[keys.index(top[0])]
    return {"consensus": consensus_output, "votes": dict(counter),
            "total_agents": len(agent_ids), "participated": len(outputs)}


def cascade(store: Store, pipeline: list[dict], input_text: str = "",
            current_user: dict | None = None) -> list[dict]:
    """级联管道：前序 Agent 输出作为后续输入。
    pipeline: [{"agent_id": 1, "mode": "single"}, {"agent_id": [2,3], "mode": "vote"}, ...]
    """
    results = []
    prev_output = input_text
    for step in pipeline:
        aids = step["agent_id"]
        mode = step.get("mode", "single")
        if mode == "vote" and isinstance(aids, list):
            r: Any = vote(store, aids, prev_output, current_user)
            prev_output = r.get("consensus", "")
            results.append({"step": step, "result": r, "mode": "vote"})
        elif isinstance(aids, list):
            r = run_parallel(store, aids, prev_output, current_user)
            prev_output = r[-1]["output"] if r else ""
            results.append({"step": step, "result": r, "mode": "parallel"})
        else:
            r = run_with_llm(store, aids, prev_output, current_user)
            prev_output = r.get("reply", "")
            results.append({"step": step, "result": r, "mode": "single"})
    return results
