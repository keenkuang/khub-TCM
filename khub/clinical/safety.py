"""用药安全引擎——相互作用检查 + 剂量验证 + 禁忌匹配。"""
from __future__ import annotations

# 十八反十九畏（扩展版）
INCOMPATIBILITY_PAIRS = [
    ("乌头", "半夏"), ("乌头", "贝母"), ("乌头", "瓜蒌"), ("乌头", "白及"),
    ("甘草", "甘遂"), ("甘草", "大戟"), ("甘草", "海藻"), ("甘草", "芫花"),
    ("藜芦", "人参"), ("藜芦", "沙参"), ("藜芦", "玄参"), ("藜芦", "苦参"),
    ("川乌", "半夏"), ("川乌", "贝母"), ("草乌", "半夏"), ("草乌", "贝母"),
]

# 妊娠禁忌
PREGNANCY_CONTRAINDICATED = ["大黄", "芒硝", "桃仁", "红花", "牛膝", "附子",
                             "肉桂", "半夏", "麝香", "水蛭", "虻虫", "三棱", "莪术"]


def check_incompatibility(formulas: list[str]) -> list[str]:
    warnings = []
    text = " ".join(formulas)
    for a, b in INCOMPATIBILITY_PAIRS:
        if a in text and b in text:
            warnings.append(f"{a} 与 {b} 相反")
    return warnings


def check_pregnancy(formulas: list[str]) -> list[str]:
    warnings = []
    for h in PREGNANCY_CONTRAINDICATED:
        for f in formulas:
            if h in f:
                warnings.append(f"{h} 妊娠禁用")
                break
    return warnings


def check_dosage(herb_name: str, dosage_g: float) -> list[str]:
    warnings = []
    max_dose = {"附子": 15, "乌头": 9, "麻黄": 9, "细辛": 3, "甘遂": 1,
                "大戟": 1, "巴豆": 0.5, "麝香": 0.1, "朱砂": 0.5}
    if herb_name in max_dose and dosage_g > max_dose[herb_name]:
        warnings.append(f"{herb_name} 用量 {dosage_g}g 超过安全上限 {max_dose[herb_name]}g")
    return warnings


def check_all(formulas: list[str], is_pregnant: bool = False) -> dict:
    return {
        "incompatibilities": check_incompatibility(formulas),
        "pregnancy_warnings": check_pregnancy(formulas) if is_pregnant else [],
    }
