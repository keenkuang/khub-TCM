"""智能问诊路径——基于主诉推荐追问。"""
from __future__ import annotations

# 主诉→追问映射
INTERVIEW_MAP: dict[str, list[str]] = {
    "头痛": ["头痛部位（前额/两侧/头顶/后脑）", "疼痛性质（胀痛/刺痛/隐痛）",
             "发作时间（早晨/午后/夜间）", "伴随症状（恶心/怕光/发热）"],
    "发热": ["体温最高多少", "发热规律（持续/间歇/午后潮热）",
             "是否恶寒", "出汗情况", "口渴与否"],
    "咳嗽": ["干咳/有痰", "痰的颜色（白/黄/带血）", "咳嗽时间（早晚/夜间）",
             "是否气喘", "有无咽痛"],
    "胃痛": ["疼痛与饮食关系（饭前/饭后）", "喜按/拒按", "泛酸/嗳气",
             "大便情况", "口干/口苦"],
    "失眠": ["难以入睡/易醒/早醒", "是否多梦", "白天精神状态",
             "是否心烦易怒", "饮食与运动情况"],
    "腰痛": ["急性/慢性", "固定痛/游走痛", "与活动关系",
             "是否放射到下肢", "有无外伤史"],
    "月经不调": ["周期/经期/经量", "经色（鲜红/暗红/有块）",
               "经期伴随症状（腹痛/乳胀）", "末次月经时间", "白带情况"],
}


def get_questions(chief_complaint: str) -> list[str]:
    for keyword, questions in INTERVIEW_MAP.items():
        if keyword in chief_complaint:
            return questions
    return ["发病多久了", "主要症状的详细情况", "做过哪些检查", "之前用过什么治疗"]


def generate_interview(store, text: str) -> dict:
    questions = get_questions(text)
    return {"chief_complaint": text, "suggested_questions": questions,
            "count": len(questions)}
