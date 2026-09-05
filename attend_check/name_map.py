# -*- coding: utf-8 -*-
"""姓名标准化：别名映射 + 繁简转换（opencc 优先，内置字典兜底）+ 模糊配对建议。

设计目标：后续新增人员出现任何简繁/写法差异都能轻松应付。
- 优先使用 opencc（专业繁简转换，覆盖全部汉字），新增人员含生僻繁体字也能转换
- opencc 不可用时回退到内置字典
- 精确配对失败时提供模糊配对建议（相似度排序），快速定位新别名/异体字
"""

import difflib
import json
import os

try:
    from opencc import OpenCC

    _converter = OpenCC("t2s")
    _HAS_OPENCC = True
except Exception:  # opencc 未安装
    _converter = None
    _HAS_OPENCC = False

# 内置兜底繁简映射（opencc 不可用时的最小集；覆盖常见姓氏与人名用字）
_TC2SC = {
    # 常见姓氏
    "劉": "刘", "陳": "陈", "張": "张", "趙": "赵", "黃": "黄", "吳": "吴",
    "孫": "孙", "馬": "马", "羅": "罗", "鄭": "郑", "謝": "谢", "韓": "韩",
    "馮": "冯", "蕭": "萧", "鄧": "邓", "許": "许", "呂": "吕", "蘇": "苏",
    "盧": "卢", "蔣": "蒋", "賈": "贾", "葉": "叶", "閻": "阎", "餘": "余",
    "鍾": "钟", "範": "范", "譚": "谭", "廖": "廖", "鄒": "邹", "陸": "陆",
    "顧": "顾", "錢": "钱", "湯": "汤", "喬": "乔", "賀": "贺", "賴": "赖",
    "龔": "龚", "藍": "蓝", "楊": "杨", "梁": "梁", "宋": "宋", "唐": "唐",
    "歐": "欧", "魏": "魏", "嚴": "严", "薛": "薛", "潘": "潘", "杜": "杜",
    "戴": "戴", "夏": "夏", "汪": "汪", "田": "田", "任": "任", "姜": "姜",
    "方": "方", "石": "石", "姚": "姚", "熊": "熊", "金": "金", "郝": "郝",
    "孔": "孔", "白": "白", "崔": "崔", "康": "康", "毛": "毛", "邱": "邱",
    "秦": "秦", "江": "江", "史": "史", "侯": "侯", "邵": "邵", "孟": "孟",
    "龍": "龙", "萬": "万", "段": "段", "雷": "雷", "尹": "尹", "黎": "黎",
    "易": "易", "常": "常", "武": "武", "文": "文", "辛": "辛", "甯": "宁",
    "塗": "涂", "游": "游", "溫": "温", "倪": "倪", "解": "解", "袁": "袁",
    # 人名常用字
    "偉": "伟", "強": "强", "軍": "军", "傑": "杰", "剛": "刚", "輝": "辉",
    "磊": "磊", "斌": "斌", "鵬": "鹏", "飛": "飞", "鋒": "锋", "銳": "锐",
    "誠": "诚", "國": "国", "貴": "贵", "榮": "荣", "祥": "祥", "瑞": "瑞",
    "澤": "泽", "濤": "涛", "銘": "铭", "寶": "宝", "瑩": "莹", "麗": "丽",
    "蘭": "兰", "紅": "红", "靜": "静", "潔": "洁", "樺": "桦", "樹": "树",
    "權": "权", "歡": "欢", "慶": "庆", "應": "应", "懷": "怀", "戰": "战",
    "點": "点", "齊": "齐", "華": "华", "廣": "广", "東": "东", "鳳": "凤",
    "漢": "汉", "曉": "晓", "陽": "阳", "賢": "贤", "鎮": "镇", "鎧": "铠",
    "錦": "锦", "儉": "俭", "駱": "骆", "繼": "继", "學": "学", "來": "来",
    "進": "进", "誠": "诚", "棟": "栋", "偉": "伟", "剛": "刚", "藍": "蓝",
    "楊": "杨", "樑": "梁", "蘇": "苏", "勝": "胜", "凱": "凯", "達": "达",
    "國": "国", "萬": "万", "數": "数", "帥": "帅", "剛": "刚", "輝": "辉",
    "澤": "泽", "傑": "杰", "毅": "毅", "俊": "俊", "峰": "峰", "健": "健",
    "明": "明", "亮": "亮", "平": "平", "安": "安", "民": "民", "志": "志",
    "建": "建", "福": "福", "龍": "龙", "鳳": "凤", "洪": "洪", "海": "海",
    "波": "波", "源": "源", "鑫": "鑫", "玉": "玉", "珍": "珍", "珠": "珠",
    "芳": "芳", "芬": "芬", "英": "英", "萍": "萍", "秀": "秀", "霞": "霞",
    "惠": "惠", "梅": "梅", "琳": "琳", "雪": "雪", "雯": "雯", "婷": "婷",
    "娜": "娜", "燕": "燕", "娟": "娟", "敏": "敏",
}


def to_simplified(name: str) -> str:
    """繁转简：opencc 优先，内置字典兜底。"""
    name = name or ""
    if _HAS_OPENCC:
        try:
            return _converter.convert(name)
        except Exception:
            pass
    return "".join(_TC2SC.get(ch, ch) for ch in name)


class NameMapper:
    """姓名归一化器：先查别名表，再繁简转换；支持模糊配对建议。"""

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

    def suggest_match(self, name: str, candidates: list[str],
                      threshold: float = 0.55, top: int = 3) -> list[tuple[str, str, float]]:
        """从未配对名单中找最可能的配对对象（模糊匹配，相似度降序）。

        返回 [(候选原名, 归一化后, 相似度)]。用于定位新人员的别名/异体字写法，
        相似度 ≥ threshold 才返回；已在别名表或可精确转换的会被跳过。
        """
        norm = self.normalize(name)
        scored: list[tuple[str, str, float]] = []
        for c in candidates:
            cn = self.normalize(c)
            if cn == norm:
                continue  # 已能精确配对，无需建议
            score = difflib.SequenceMatcher(None, norm, cn).ratio()
            scored.append((c, cn, round(score, 3)))
        scored.sort(key=lambda x: -x[2])
        return [s for s in scored if s[2] >= threshold][:top]
