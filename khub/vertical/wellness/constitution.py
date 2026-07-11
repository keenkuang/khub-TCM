"""养生保健——9 种体质评估 + 养生建议。"""
from __future__ import annotations

CONSTITUTIONS = {
    "平和质": {"score_range": (0, 20), "advice": "体质平和，保持规律作息、均衡饮食、适度运动。",
              "diet": "均衡饮食，五谷为养", "exercise": "每周 3-5 次有氧运动"},
    "气虚质": {"score_range": (21, 40), "advice": "补气健脾，避免过度劳累。推荐四君子汤加减。",
              "diet": "宜食山药、大枣、黄芪炖鸡", "exercise": "八段锦、太极拳，避免大汗"},
    "阳虚质": {"score_range": (21, 40), "advice": "温阳散寒，注意保暖。推荐金匮肾气丸。",
              "diet": "宜食羊肉、韭菜、生姜", "exercise": "日光浴、快走，避免冬泳"},
    "阴虚质": {"score_range": (21, 40), "advice": "滋阴降火，避免熬夜。推荐六味地黄丸。",
              "diet": "宜食百合、银耳、鸭肉", "exercise": "瑜伽、游泳，避免剧烈运动"},
    "痰湿质": {"score_range": (21, 40), "advice": "健脾祛湿，控制体重。推荐二陈汤加减。",
              "diet": "宜食薏米、冬瓜、赤小豆", "exercise": "有氧运动为主，出汗为度"},
    "湿热质": {"score_range": (21, 40), "advice": "清热利湿，忌辛辣。推荐甘露消毒丹。",
              "diet": "宜食绿豆、苦瓜、薏米", "exercise": "强度适中，避免闷热环境"},
    "血瘀质": {"score_range": (21, 40), "advice": "活血化瘀，保持情绪舒畅。推荐血府逐瘀汤。",
              "diet": "宜食山楂、黑豆、醋", "exercise": "拉伸运动、舞蹈，促进循环"},
    "气滞质": {"score_range": (21, 40), "advice": "疏肝理气，调节情绪。推荐逍遥散。",
              "diet": "宜食萝卜、玫瑰花茶、柑橘", "exercise": "瑜伽、太极，配合深呼吸"},
    "特禀质": {"score_range": (21, 40), "advice": "增强免疫，避免过敏原。推荐玉屏风散。",
              "diet": "宜食灵芝、黄芪、蜂蜜", "exercise": "温和运动，避免花粉季节户外运动"},
}


# 简易评估问卷（9 题，每题 1-5 分）
QUESTIONS = [
    {"id": 1, "text": "您经常感到精力充沛吗？", "type": "reverse"},
    {"id": 2, "text": "您容易疲劳、气短、懒得说话吗？", "type": "qi"},
    {"id": 3, "text": "您怕冷、手脚冰凉吗？", "type": "yang"},
    {"id": 4, "text": "您手心脚心发热、口干咽燥吗？", "type": "yin"},
    {"id": 5, "text": "您感觉身体沉重、容易困倦吗？", "type": "tan"},
    {"id": 6, "text": "您容易口苦、小便黄吗？", "type": "shi_re"},
    {"id": 7, "text": "您皮肤容易瘀青、面色晦暗吗？", "type": "xue_yu"},
    {"id": 8, "text": "您容易情绪低落、胁肋胀痛吗？", "type": "qi_zhi"},
    {"id": 9, "text": "您容易过敏（皮肤/呼吸道）吗？", "type": "te_bing"},
]

# 简单判定规则
_RULE_MAP: dict[str, str] = {
    "qi": "气虚质", "yang": "阳虚质", "yin": "阴虚质",
    "tan": "痰湿质", "shi_re": "湿热质", "xue_yu": "血瘀质",
    "qi_zhi": "气滞质", "te_bing": "特禀质",
}


def assess(answers: dict[str, int]) -> dict:
    """根据问卷答案评估体质。answers: {question_type: score(1-5)}。"""
    # 计算各体质倾向得分
    scores: dict[str, int] = {"ping_he": 0}
    for qtype, score in answers.items():
        if qtype == "reverse":
            scores["ping_he"] = scores.get("ping_he", 0) + (6 - score)
        elif qtype in _RULE_MAP:
            scores[_RULE_MAP[qtype]] = scores.get(_RULE_MAP[qtype], 0) + score
    scores["平和质"] = scores.pop("ping_he", 0)

    # 判定主体质（最高分）
    main_type = max(scores, key=lambda k: scores.get(k, 0))
    const = CONSTITUTIONS.get(main_type, CONSTITUTIONS["平和质"])
    return {
        "primary_constitution": main_type,
        "scores": scores,
        "advice": const["advice"],
        "diet": const["diet"],
        "exercise": const["exercise"],
    }


def get_questions() -> list[dict]:
    return QUESTIONS
