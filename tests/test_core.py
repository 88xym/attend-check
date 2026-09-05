# -*- coding: utf-8 -*-
"""核心逻辑单元测试（不依赖真实数据文件）。"""

import unittest

from attend_check.name_map import NameMapper, to_simplified


class TestNameMap(unittest.TestCase):
    def test_to_simplified(self):
        self.assertEqual(to_simplified("葉書豪"), "叶书豪")
        self.assertEqual(to_simplified("陳曉東"), "陈晓东")
        self.assertEqual(to_simplified("劉志強"), "刘志强")

    def test_to_simplified_new_chars(self):
        """新增人员的生僻姓氏也应能转换（opencc 全覆盖）。"""
        self.assertEqual(to_simplified("譚詠琳"), "谭咏琳")
        self.assertEqual(to_simplified("黃嘉敏"), "黄嘉敏")
        self.assertEqual(to_simplified("龔志明"), "龚志明")

    def test_mapper_normalize(self):
        m = NameMapper()
        self.assertEqual(m.normalize("葉書豪"), "叶书豪")
        self.assertEqual(m.normalize("叶书豪"), "叶书豪")

    def test_mapper_alias(self):
        import json
        import os
        import tempfile

        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump({"aliases": {"李明机场": "李明"}}, f, ensure_ascii=False)
            p = f.name
        try:
            m = NameMapper(p)
            self.assertEqual(m.normalize("李明机场"), "李明")
        finally:
            os.unlink(p)

    def test_suggest_match(self):
        """配对不上时给出模糊建议，便于发现新别名/异体字。"""
        m = NameMapper()
        # 一字之差的写法 -> 应给出建议，且最相似者排最前
        hits = m.suggest_match("杜子航", ["杜子恒", "杜子涵"])
        self.assertTrue(hits)
        self.assertEqual(hits[0][1], "杜子恒")
        # 完全不同的名字不应命中
        hits2 = m.suggest_match("张三", ["李四", "王五", "赵六"])
        self.assertEqual(hits2, [])

    def test_suggest_match_skip_exact(self):
        """已能精确归一化的候选不再作为建议返回。"""
        m = NameMapper()
        hits = m.suggest_match("陈晓东", ["陳曉東", "陈晓东"])
        self.assertEqual(hits, [])  # 两者归一化后相同 -> 无需建议


if __name__ == "__main__":
    unittest.main()
