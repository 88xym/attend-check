# -*- coding: utf-8 -*-
"""姓名标准化：繁简映射 + 别名映射。

考勤原始记录与手工考勤表存在繁简体混用（如 叶书豪/葉書豪），
不能直接字符串比对，统一归一到简体后再匹配。
工号是更可靠的键，但考勤表未含工号列，因此以“归一化姓名”为主键。
"""

import json
import os

# 常见繁简字符映射（覆盖本项目涉及姓名用字及常用字）
_TC2SC = {
    "駱": "骆", "張": "张", "學": "学", "軍": "军", "鄒": "邹", "繼": "继",
    "陳": "陈", "來": "来", "進": "进", "趙": "赵", "呂": "吕", "誠": "诚",
    "棟": "栋", "強": "强", "偉": "伟", "剛": "刚", "藍": "蓝", "楊": "杨",
    "輝": "辉", "澤": "泽", "凱": "凯", "達": "达", "國": "国", "萬": "万",
    "勝": "胜", "傑": "杰", "樑": "梁", "蘇": "苏", "華": "华", "廣": "广",
    "東": "东", "龍": "龙", "鳳": "凤", "漢": "汉", "曉": "晓", "陽": "阳",
    "榮": "荣", "賢": "贤", "貴": "贵", "鎮": "镇", "鎧": "铠", "鋒": "锋",
    "銘": "铭", "錦": "锦", "儉": "俭", "瑩": "莹", "潔": "洁", "樺": "桦",
    "樹": "树", "權": "权", "歡": "欢", "慶": "庆", "應": "应", "懷": "怀",
    "戰": "战", "點": "点", "齊": "齐", "麗": "丽", "蘭": "兰", "葉": "叶",
    "歐": "欧", "龔": "龚", "羅": "罗", "馬": "马", "王": "王", "蘇": "苏",
}


def to_simplified(name: str) -> str:
    """把字符串中的繁体字转简体（逐字符映射）。"""
    return "".join(_TC2SC.get(ch, ch) for ch in (name or ""))


class NameMapper:
    """姓名归一化器：先查别名表，再繁简转换。"""

    def __init__(self, alias_file: str | None = None):
        self.alias: dict[str, str] = {}
        if alias_file and os.path.exists(alias_file):
            with open(alias_file, encoding="utf-8") as f:
                data = json.load(f)
            raw = data.get("aliases", {}) if isinstance(data, dict) else {}
            self.alias = {str(k).strip(): str(v).strip() for k, v in raw.items()}

    def normalize(self, name: str) -> str:
        name = (name or "").strip()
        if not name:
            return name
        if name in self.alias:
            return self.alias[name]
        return to_simplified(name)
