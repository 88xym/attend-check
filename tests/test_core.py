# -*- coding: utf-8 -*-
"""核心逻辑单元测试（不依赖真实数据文件）。"""

import unittest
from datetime import date, datetime

from attend_check.loader import AttendanceTable, DayRecord, MonthTotals
from attend_check.name_map import NameMapper, to_simplified
from attend_check.rules import check_presence, check_totals


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


class TestWeekendRules(unittest.TestCase):
    """周末考勤规则：周一~周五全天、周六半天、周日休息。"""

    def _mk(self):
        t = AttendanceTable(date(2026, 8, 1), date(2026, 8, 31))
        t.date_cols = {4: date(2026, 8, 8), 5: date(2026, 8, 9), 6: date(2026, 8, 10)}
        t.days["张三"] = {
            date(2026, 8, 8): DayRecord(mark_up="√"),            # 周六半天
            date(2026, 8, 9): DayRecord(mark_up="√", mark_down="√"),  # 周日休息日
            date(2026, 8, 10): DayRecord(mark_up="√", mark_down="√"), # 周一
        }
        return t

    def test_saturday_single_punch_not_missing(self):
        """周六半天班，仅 1 次打卡不报缺卡提醒。"""
        t = self._mk()
        punch_idx = {"张三": {
            date(2026, 8, 8): [datetime(2026, 8, 8, 8, 15)],   # 周六上午 1 次
            date(2026, 8, 9): [datetime(2026, 8, 9, 8, 30)],   # 周日
            date(2026, 8, 10): [datetime(2026, 8, 10, 8, 20)],  # 周一
        }}
        diffs = check_presence(punch_idx, t, NameMapper())
        by_date = {(d.on_date, d.category) for d in diffs}
        self.assertNotIn((date(2026, 8, 8), "缺卡提醒"), by_date)   # 周六豁免
        self.assertIn((date(2026, 8, 10), "缺卡提醒"), by_date)     # 周一报缺卡
        self.assertIn((date(2026, 8, 9), "周日出勤核对"), by_date)  # 周日√需佐证

    def test_sunday_check_without_restday_hours(self):
        """周日有√且无休息日上班数字 -> 周日出勤核对。"""
        t = self._mk()
        punch_idx = {"张三": {date(2026, 8, 9): [datetime(2026, 8, 9, 8, 30), datetime(2026, 8, 9, 17, 0)]}}
        diffs = check_presence(punch_idx, t, NameMapper())
        self.assertTrue(any(d.category == "周日出勤核对" for d in diffs))

    def test_sunday_with_hours_ok(self):
        """周日有休息日上班数字时，不再报周日出勤核对。"""
        t = AttendanceTable(date(2026, 8, 1), date(2026, 8, 31))
        t.date_cols = {5: date(2026, 8, 9)}
        t.days["张三"] = {date(2026, 8, 9): DayRecord(mark_up="4", mark_down="4", h_up=4, h_down=4)}
        punch_idx = {"张三": {date(2026, 8, 9): [datetime(2026, 8, 9, 8, 30), datetime(2026, 8, 9, 12, 0)]}}
        diffs = check_presence(punch_idx, t, NameMapper())
        self.assertFalse(any(d.category == "周日出勤核对" for d in diffs))


class TestLeaveGrouping(unittest.TestCase):
    """產/喪/婚 归入"其（d)"列统计。"""

    def test_chan_sang_hun_into_qi(self):
        t = AttendanceTable(date(2026, 8, 1), date(2026, 8, 31))
        t.date_cols = {4: date(2026, 8, 3)}  # 周一
        t.days["李四"] = {date(2026, 8, 3): DayRecord(mark_up="产", mark_down="产")}
        t.totals["李四"] = MonthTotals(name="李四", other_d=1.0)  # 其（d)=1
        diffs = check_totals(t)
        # 产 标记 2 个 × 0.5 = 1 天，与月度"其"=1 一致 -> 无差异
        self.assertEqual(diffs, [])


if __name__ == "__main__":
    unittest.main()
