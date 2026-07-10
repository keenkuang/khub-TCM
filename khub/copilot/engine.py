"""Copilot 执行引擎——意图→工具选择→执行→回复。"""
from __future__ import annotations
import json
from ..db import Store
from .intents import parse as parse_intent


def process(store: Store, text: str, current_user: dict | None = None) -> dict:
    from . import tools as tool_registry
    intent = parse_intent(text)
    intent_name = intent.get("intent", "help")
    entities = intent.get("entities", {})

    if intent_name == "help":
        tool_list = tool_registry.list_tools()
        reply = "我可以帮你做这些事情：\n" + "\n".join(
            f"- **{t['name']}**：{t['description']}" for t in tool_list)
        return {"reply": reply, "tool_used": None}

    tool = tool_registry.get(intent_name)
    if not tool:
        return {"reply": f"抱歉，我不支持'{intent_name}'操作。输入'帮助'查看我可以做什么。",
                "tool_used": None}

    result = tool_registry.call_tool(intent_name, entities, store, current_user)
    reply = f"已执行「{tool.description}」：\n{result}" if not result.startswith("错误") else result
    return {"reply": reply, "tool_used": intent_name, "entities": entities}
