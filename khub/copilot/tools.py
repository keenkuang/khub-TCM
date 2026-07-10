"""工具注册表——定义和执行可调用的操作。"""
from __future__ import annotations
import json
from typing import Any, Callable


class Tool:
    def __init__(self, name: str, description: str, parameters: list[dict],
                 execute: Callable):
        self.name = name
        self.description = description
        self.parameters = parameters
        self.execute = execute

    def to_dict(self) -> dict:
        return {"name": self.name, "description": self.description,
                "parameters": self.parameters}


_registry: dict[str, Tool] = {}


def register(tool: Tool):
    _registry[tool.name] = tool


def get(name: str) -> Tool | None:
    return _registry.get(name)


def list_tools() -> list[dict]:
    return [t.to_dict() for t in _registry.values()]


def call_tool(name: str, params: dict, store, current_user=None) -> str:
    tool = get(name)
    if not tool:
        return f"错误：未知工具 '{name}'"
    try:
        result = tool.execute(store, current_user, **params)
        if isinstance(result, str):
            return result
        return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception as e:
        return f"执行失败：{e}"


# ── 工具定义 ──

def _search_docs(store, current_user, q="", k=5):
    from ..retrieval import Retriever
    results = Retriever(store).search_similar(q, limit=k)
    if not results: return "未找到相关文档"
    return "\n".join(f"- {r.get('title','')} (相似度:{r.get('score',0):.2f})" for r in results[:k])


def _get_patient(store, current_user, patient=""):
    if patient.isdigit():
        row = store.conn.execute("SELECT id, name, gender, born FROM patients WHERE id=?", (int(patient),)).fetchone()
    else:
        row = store.conn.execute("SELECT id, name, gender, born FROM patients WHERE name LIKE ?", (f"%{patient}%",)).fetchone()
    if not row: return "未找到患者"
    return f"患者 #{row['id']}：{row['name']} {'男' if row['gender']=='male' else '女'} ({row['born'] or ''})"


def _book_appointment(store, current_user, patient="", date="", doctor=""):
    from ..ops.store import book_appointment
    pid = int(patient) if patient.isdigit() else 1
    aid = book_appointment(store, pid, date or "2026-08-01", doctor or "值班医生")
    return f"预约 #{aid} 已创建"


def _list_courses(store, current_user, status=""):
    from ..course.store import list_courses
    courses = list_courses(store, status=status or None)
    if not courses: return "暂无课程"
    return "\n".join(f"- #{c['id']} {c['name']} {c['teacher'] or ''} [{c['status']}]" for c in courses[:10])


def _query_knowledge_graph(store, current_user, syndrome=""):
    from ..knowledge.inference import infer
    result = infer(store, syndrome)
    if "error" in result: return result["error"]
    return (f"证型：{result['syndrome']}\n治法：{', '.join(result['treatment_methods'])}\n"
            f"推荐方剂：{', '.join(result['recommended_formulas'])}\n"
            f"归经：{', '.join(result['channel_tropism'])}")


def _create_notification(store, current_user, user_id="", title=""):
    from ..notifications import create
    uid = int(user_id) if user_id and user_id.isdigit() else 1
    nid = create(store, uid, title or "Copilot 通知", body="由 AI 助手创建", event_type="copilot")
    return f"通知 #{nid} 已发送"


def _run_report(store, current_user, template_id=""):
    from ..reports import execute
    tid = int(template_id) if template_id and template_id.isdigit() else None
    if not tid: return "请指定报表 ID"
    result = execute(store, tid)
    return f"报表 '{result['name']}': {result['row_count']} 行数据"


def _help_tool(store, current_user):
    tools = list_tools()
    return "我可以帮你做这些事情：\n" + "\n".join(f"- {t['name']}: {t['description']}" for t in tools)


# ── 注册工具 ──
register(Tool("search_docs", "搜索文档", [{"name":"q","type":"string","required":True}], _search_docs))
register(Tool("get_patient", "查询患者信息", [{"name":"patient","type":"string","required":True}], _get_patient))
register(Tool("book_appointment", "预约挂号", [{"name":"patient","type":"string"},{"name":"date","type":"string"},{"name":"doctor","type":"string"}], _book_appointment))
register(Tool("list_courses", "查看课程列表", [{"name":"status","type":"string"}], _list_courses))
register(Tool("query_knowledge_graph", "查询中医知识图谱", [{"name":"syndrome","type":"string","required":True}], _query_knowledge_graph))
register(Tool("create_notification", "发送通知", [{"name":"user_id","type":"string"},{"name":"title","type":"string","required":True}], _create_notification))
register(Tool("run_report", "运行报表", [{"name":"template_id","type":"string","required":True}], _run_report))
register(Tool("help", "查看帮助信息", [], _help_tool))
