"""工作流状态机引擎。"""
from __future__ import annotations
import json
import logging
from datetime import datetime
from ..db import Store
from .store import get_definition, get_instance

logger = logging.getLogger("khub.workflow")


def run(store: Store, instance_id: int) -> dict:
    """执行工作流实例，步进到完成或阻塞。"""
    instance = get_instance(store, instance_id)
    if not instance: raise ValueError("实例不存在")
    definition = get_definition(store, instance["definition_id"])
    if not definition: raise ValueError("定义不存在")

    steps = json.loads(definition["steps"]) if isinstance(definition["steps"], str) else definition["steps"]
    context = json.loads(instance["context"]) if isinstance(instance.get("context"), str) else (instance.get("context") or {})
    history = json.loads(instance["history"]) if isinstance(instance.get("history"), str) else (instance.get("history") or [])
    current = instance["current_step"] or (steps[0]["name"] if steps else "")

    while current and current != "__end__":
        step_def = next((s for s in steps if s["name"] == current), None)
        if not step_def:
            _update(store, instance_id, status="failed", context=context, history=history + [{"step": current, "error": "step not found"}])
            return {"status": "failed", "error": f"step '{current}' not found"}
        try:
            result = _execute_step(step_def, context, store)
            history.append({"step": current, "result": result.get("output", "")})
            if result.get("status") == "failed":
                _update(store, instance_id, status="failed", context=context, history=history)
                return result
            current = result.get("next", step_def.get("next", "__end__"))
            context.update(result.get("context_updates", {}))
        except Exception as e:
            logger.warning("工作流步骤 %s 失败: %s", current, e)
            _update(store, instance_id, status="failed", context=context, history=history + [{"step": current, "error": str(e)}])
            return {"status": "failed", "error": str(e)}

    _update(store, instance_id, status="completed", context=context, history=history, current_step=None)
    return {"status": "completed"}


def _execute_step(step: dict, context: dict, store) -> dict:
    t = step.get("type", "auto")
    config = step.get("config", {})
    if t == "auto":
        action = config.get("action", "")
        params = {k: _resolve(v, context) for k, v in config.get("params", {}).items()}
        output = _call_action(action, params, store)
        return {"status": "ok", "output": output, "next": step.get("next", "__end__")}
    elif t == "condition":
        expr = config.get("expression", "")
        branches = config.get("branches", {})
        result = _evaluate(expr, context)
        next_step = branches.get(str(result), branches.get("_default", "__end__"))
        return {"status": "ok", "output": f"condition: {expr} = {result}", "next": next_step, "context_updates": {f"condition.{expr}": result}}
    elif t == "notify":
        from ..notifications import create
        title = _resolve(config.get("title", "工作流通知"), context)
        body = _resolve(config.get("body", ""), context)
        create(store, int(config.get("user_id", 0)), title, body, event_type="workflow")
        return {"status": "ok", "output": f"notification sent", "next": step.get("next", "__end__")}
    return {"status": "ok", "next": step.get("next", "__end__")}


def _resolve(value: str, context: dict) -> str:
    import re
    def repl(m):
        key = m.group(1)
        return str(context.get(key, m.group(0)))
    return re.sub(r"\$\{(\w+)\}", repl, str(value))


def _evaluate(expr: str, context: dict) -> bool:
    resolved = _resolve(expr, context)
    return resolved.lower() in ("true", "yes", "1")


def _call_action(action: str, params: dict, store):
    from ..notifications import create as _notify
    from ..reports import create_template, execute
    if action == "create_notification":
        _notify(store, int(params.get("user_id", 0)), params.get("title", ""), params.get("body", ""), event_type="workflow")
        return "notification created"
    elif action == "run_report":
        tid = int(params.get("template_id", 0))
        result = execute(store, tid)
        return f"report executed: {result.get('row_count', 0)} rows"
    raise ValueError(f"工作流 action 未注册: '{action}'。支持的 action: create_notification, run_report")


def _update(store, instance_id, status=None, context=None, history=None, current_step=None):
    updates = {}
    if status: updates["status"] = status
    if context is not None: updates["context"] = json.dumps(context, ensure_ascii=False)
    if history is not None: updates["history"] = json.dumps(history, ensure_ascii=False)
    if current_step is not None: updates["current_step"] = current_step
    if status in ("completed", "failed"): updates["completed_at"] = datetime.now().isoformat()
    if not updates: return
    set_clause = ", ".join(f"{k}=?" for k in updates)
    store.conn.execute(f"UPDATE workflow_instances SET {set_clause} WHERE id=?", (*updates.values(), instance_id))
