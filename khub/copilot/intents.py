"""意图识别——将自然语言解析为意图+实体。"""
from __future__ import annotations
import json
import re

_INTENT_PATTERNS: list[tuple[str, str, list[str]]] = [
    ("search_docs", r"搜索|查找|查询.*文档|找.*资料|搜.*文章", ["q"]),
    ("get_patient", r"查询.*患者|查看.*病人|患者信息|病人资料", ["patient"]),
    ("book_appointment", r"预约|挂号|约诊|预约.*医生", ["patient", "date", "doctor"]),
    ("list_courses", r"课程列表|查看课程|有哪些课程|课程安排", []),
    ("query_knowledge_graph", r"辨证|证型|方剂|知识图谱|中医.*推荐", ["syndrome"]),
    ("create_notification", r"发送通知|通知|提醒.*用户", ["user_id", "title"]),
    ("run_report", r"运行报表|报表|数据统计|生成报告", ["template_id"]),
    ("help", r"帮助|功能|你可以做什么|支持哪些|help", []),
]


def parse(text: str, provider=None) -> dict:
    """解析用户输入，返回{'intent':str, 'entities':dict, 'confidence':str}。"""
    # 先尝试 LLM
    if provider and hasattr(provider, 'complete'):
        try:
            prompt = (
                f"从用户的请求中提取意图和参数。可用意图：search_docs(搜索文档), "
                f"get_patient(查询患者), book_appointment(预约挂号), "
                f"list_courses(课程列表), query_knowledge_graph(知识图谱查询), "
                f"create_notification(发送通知), run_report(运行报表), help(帮助)。\n"
                f"用户输入：{text}\n"
                f"以 JSON 返回：{{\"intent\":\"...\", \"entities\":{{}}}}"
            )
            result = provider.complete(prompt) or ""
            m = re.search(r"\{.*\}", result, re.DOTALL)
            if m:
                data = json.loads(m.group())
                if data.get("intent"):
                    return {**data, "confidence": "high"}
        except Exception:
            pass
    # 离线回退：正则匹配
    for intent, pattern, _ in _INTENT_PATTERNS:
        if re.search(pattern, text):
            entities = _extract_entities(text, intent)
            return {"intent": intent, "entities": entities, "confidence": "medium"}
    return {"intent": "help", "entities": {}, "confidence": "low"}


def _extract_entities(text: str, intent: str) -> dict:
    """从文本中提取实体（规则/关键词）。"""
    entities: dict[str, str] = {}
    date_m = re.search(r"(\d{4}[-/]\d{1,2}[-/]\d{1,2})", text)
    if date_m: entities["date"] = date_m.group(1)
    doctor_m = re.search(r"([\u674e\u738b\u5f20\u674e\u5218\u9648\u6768\u9ec4\u5468\u5434\u5f90\u5b59\u9a6c\u80e1\u67f3\u4f55])\u533b\u751f|找(.{1,4})\u533b\u751f", text)
    if doctor_m: entities["doctor"] = doctor_m.group(1) or doctor_m.group(2) or ""
    entity_keywords = {
        "query_knowledge_graph": ["syndrome", r"(风寒|风热|寒湿|湿热|痰湿|气滞|血瘀|气虚|血虚|阴虚|阳虚|脾虚|肾虚|肝郁)(?:证|)?"],
    }
    if intent in entity_keywords:
        key, pat = entity_keywords[intent]
        m = re.search(pat, text)
        if m: entities[key] = m.group(1)
    return entities
