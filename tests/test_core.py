# -*- coding: utf-8 -*-
"""核心逻辑单元测试（不依赖真实数据文件）。"""

import unittest
from datetime import date

from attend_check.name_map import NameMapper, to_simplified


class TestNameMap(unittest.TestCase):
    def test_to_simplified(self):
        self.assertEqual(to_simplified("駱增毅"), "骆增毅")
        self.assertEqual(to_simplified("張學軍"), "张学军")
        self.assertEqual(to_simplified("陳來進"), "陈来进")

    def test_mapper_normalize(self):
        m = NameMapper()
        self.assertEqual(m.normalize("駱增毅"), "骆增毅")
        self.assertEqual(m.normalize("骆增毅"), "骆增毅")

    def test_mapper_alias(self):
        import json, tempfile, os
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump({"aliases": {"王文彬机场": "王文彬"}}, f, ensure_ascii=False)
            p = f.name
        try:
            m = NameMapper(p)
            self.assertEqual(m.normalize("王文彬机场"), "王文彬")
        finally:
            os.unlink(p)


if __name__ == "__main__":
    unittest.main()
