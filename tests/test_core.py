# -*- coding: utf-8 -*-
"""核心逻辑单元测试（不依赖真实数据文件）。"""

import unittest

from attend_check.name_map import NameMapper, to_simplified


class TestNameMap(unittest.TestCase):
    def test_to_simplified(self):
        self.assertEqual(to_simplified("駱增毅"), "骆增毅")
        self.assertEqual(to_simplified("張學軍"), "张学军")
        self.assertEqual(to_simplified("陳來進"), "陈来进")

    def test_to_simplified_new_chars(self):
        """新增人员的生僻姓氏也应能转换（opencc 全覆盖）。"""
        self.assertEqual(to_simplified("劉德華"), "刘德华")
        self.assertEqual(to_simplified("黃志強"), "黄志强")
        self.assertEqual(to_simplified("龔建國"), "龚建国")

    def test_mapper_normalize(self):
        m = NameMapper()
        self.assertEqual(m.normalize("駱增毅"), "骆增毅")
        self.assertEqual(m.normalize("骆增毅"), "骆增毅")

    def test_mapper_alias(self):
        import json
        import os
        import tempfile

        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump({"aliases": {"王文彬机场": "王文彬"}}, f, ensure_ascii=False)
            p = f.name
        try:
            m = NameMapper(p)
            self.assertEqual(m.normalize("王文彬机场"), "王文彬")
        finally:
            os.unlink(p)

    def test_suggest_match(self):
        """配对不上时给出模糊建议，便于发现新别名/异体字。"""
        m = NameMapper()
        # 一字之差的写法 -> 应给出建议，且最相似者排最前
        hits = m.suggest_match("吴南成", ["吴南承", "张南成"])
        self.assertTrue(hits)
        self.assertEqual(hits[0][1], "吴南承")
        # 完全不同的名字不应命中
        hits2 = m.suggest_match("张三", ["李四", "王五", "赵六"])
        self.assertEqual(hits2, [])

    def test_suggest_match_skip_exact(self):
        """已能精确归一化的候选不再作为建议返回。"""
        m = NameMapper()
        hits = m.suggest_match("张学军", ["張學軍", "张学军"])
        self.assertEqual(hits, [])  # 两者归一化后相同 -> 无需建议


if __name__ == "__main__":
    unittest.main()
