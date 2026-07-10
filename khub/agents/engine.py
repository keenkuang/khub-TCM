"""Agent 执行引擎——工具选择 + 链式调用。"""
from __future__ import annotations
import json
from ..db import Store
from ..copilot.tools import call_tool, list_tools
from .store import get_agent


def run(store: Store, agent_id: int, user_input: str = "", current_user: dict | None = None) -> dict:
    agent = get_agent(store, agent_id)
    if not agent:
        raise ValueError("Agent 不存在")
    tools = json.loads(agent["tools"]) if isinstance(agent["tools"], str) else (agent["tools"] or [])
    system_prompt = agent["system_prompt"] or ""
    # 构建 prompt
    prompt = f"{system_prompt}\n\n用户输入：{user_input}" if system_prompt else user_input
    # 执行工具链
    results = []
    for tool_name in tools:
        tool = call_tool(tool_name, {"q": user_input} if tool_name == "search_docs" else {}, store, current_user)
        results.append({"tool": tool_name, "result": tool})
    return {"agent_id": agent_id, "agent_name": agent["name"], "results": results,
            "tools_executed": tools, "output": "\n".join(str(r.get("result", "")) for r in results)}


def run_with_llm(store: Store, agent_id: int, user_input: str = "",
                 current_user: dict | None = None) -> dict:
    """LLM 驱动的 Agent 执行。"""
    from ..llm import get_provider
    agent = get_agent(store, agent_id)
    if not agent:
        raise ValueError("Agent 不存在")
    tools = json.loads(agent["tools"]) if isinstance(agent["tools"], str) else (agent["tools"] or [])
    provider = get_provider()
    tool_descriptions = "\n".join(f"- {t['name']}: {t['description']}" for t in list_tools())
    prompt = (
        f"{agent['system_prompt'] or '你是一个 AI 助手，可以根据用户需求选择合适的工具来执行。'}\n\n"
        f"可用工具：\n{tool_descriptions}\n\n"
        f"用户需求：{user_input}\n\n请选择合适的工具并执行，然后向用户汇报结果。")
    try:
        reply = provider.complete(prompt) or ""
    except Exception:
        reply = ""
    return {"agent_id": agent_id, "agent_name": agent["name"], "reply": reply or "（离线模式，无法调用 LLM）", "llm_driven": True}
