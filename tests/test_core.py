# -*- coding: utf-8 -*-
"""核心逻辑单元测试（不依赖真实数据文件）。"""

import unittest
from datetime import date

from attend_check.name_map import NameMapper, to_simplified


class TestNameMap(unittest.TestCase):
    def test_to_simplified(self):
        self.assertEqual(to_simplified("葉書豪"), "叶书豪")
        self.assertEqual(to_simplified("陳曉東"), "陈晓东")
        self.assertEqual(to_simplified("劉志強"), "刘志强")

    def test_mapper_normalize(self):
        m = NameMapper()
        self.assertEqual(m.normalize("葉書豪"), "叶书豪")
        self.assertEqual(m.normalize("叶书豪"), "叶书豪")

    def test_mapper_alias(self):
        import json, tempfile, os
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump({"aliases": {"李明机场": "李明"}}, f, ensure_ascii=False)
            p = f.name
        try:
            m = NameMapper(p)
            self.assertEqual(m.normalize("李明机场"), "李明")
        finally:
            os.unlink(p)


if __name__ == "__main__":
    unittest.main()
