"""Agent 模板市场——5 个预置模板 + CRUD。"""
from __future__ import annotations
import json
from ..db import Store

TEMPLATES = [
    {"name": "健康助手", "category": "健康", "description": "查询患者信息、搜索相关文档、预约挂号",
     "system_prompt": "你是一个健康助手，帮助用户查询健康信息和管理就诊。",
     "tools": ["get_patient", "search_docs", "book_appointment"]},
    {"name": "辨证助手", "category": "中医", "description": "查询证型推荐方剂、搜索中药知识",
     "system_prompt": "你是中医辨证助手，帮助用户理解证型、方剂和中药。",
     "tools": ["query_knowledge_graph", "search_docs"]},
    {"name": "预约助手", "category": "运营", "description": "管理预约、查看课程列表、发送通知",
     "system_prompt": "你是预约管理助手。",
     "tools": ["book_appointment", "list_courses", "create_notification"]},
    {"name": "搜索助手", "category": "知识", "description": "跨实体搜索文档和知识",
     "system_prompt": "你是知识搜索助手。",
     "tools": ["search_docs", "help"]},
    {"name": "报表助手", "category": "分析", "description": "运行报表、分析数据趋势",
     "system_prompt": "你是数据分析助手。",
     "tools": ["run_report", "help"]},
]


def seed(store: Store):
    if store.conn.execute("SELECT 1 FROM agent_templates").fetchone(): return
    for t in TEMPLATES:
        store.conn.execute(
            "INSERT INTO agent_templates (name, category, description, system_prompt, tools, config) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (t["name"], t["category"], t["description"], t["system_prompt"],
             json.dumps(t["tools"]), "{}"))


def list_templates(store: Store, category: str = "") -> list[dict]:
    if category: return store.conn.execute("SELECT * FROM agent_templates WHERE category=? ORDER BY name", (category,)).fetchall()
    return store.conn.execute("SELECT * FROM agent_templates ORDER BY category, name").fetchall()


def create_from_template(store: Store, template_id: int, name: str = "") -> int:
    tpl = store.conn.execute("SELECT * FROM agent_templates WHERE id=?", (template_id,)).fetchone()
    if not tpl: raise ValueError("模板不存在")
    from .store import create_agent
    agent_name = name or tpl["name"]
    tools = json.loads(tpl["tools"]) if isinstance(tpl["tools"], str) else (tpl["tools"] or [])
    return create_agent(store, agent_name, system_prompt=tpl["system_prompt"], tools=tools, description=tpl["description"])
