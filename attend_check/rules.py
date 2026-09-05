# -*- coding: utf-8 -*-
"""阶段一对账规则引擎。

规则组 A：到场核对 —— 打卡记录 vs 考勤表标记（每人每天）
规则组 B：累计重算 —— 逐日标记重新求和 vs 考勤表“月度累计”列
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, time, datetime

from .loader import AttendanceTable, DayRecord, MonthTotals, Punch
from .name_map import NameMapper

# 差异严重级别
LV_HARD = "硬错误"   # 数据自相矛盾，必须修正
LV_SUSPECT = "可疑项"  # 需要人工查证


@dataclass
class Diff:
    """一条差异记录。"""

    category: str        # 规则类别
    name: str            # 姓名（已归一化）
    on_date: date | None = None
    level: str = LV_HARD
    raw_desc: str = ""   # 原始打卡侧情况
    attend_desc: str = ""  # 考勤表侧情况
    detail: str = ""     # 差异说明

    def to_row(self) -> list:
        return [self.category, self.name, self.on_date.isoformat() if self.on_date else "",
                self.level, self.raw_desc, self.attend_desc, self.detail]


@dataclass
class CheckResult:
    diffs: list[Diff] = field(default_factory=list)

    def add(self, d: Diff):
        self.diffs.append(d)

    def by_level(self) -> dict:
        out = defaultdict(int)
        for d in self.diffs:
            out[d.level] += 1
        return dict(out)

    def by_category(self) -> dict:
        out = defaultdict(int)
        for d in self.diffs:
            out[d.category] += 1
        return dict(out)


# 假期类标记（有打卡时同时出现这类标记 = 半日假，属正常，不报差异）
_LEAVE_MARKS = {"補", "年", "病", "事", "培", "差", "其", "曠", "產", "喪", "婚"}


def build_punch_index(punches: list[Punch], mapper: NameMapper) -> dict[str, dict[date, list[datetime]]]:
    """原始打卡 -> {归一化姓名: {日期: [打卡时间, ...]}}。"""
    idx: dict[str, dict[date, list[datetime]]] = defaultdict(lambda: defaultdict(list))
    for p in punches:
        nm = mapper.normalize(p.name)
        idx[nm][p.punch_time.date()].append(p.punch_time)
    for nm in idx:
        for d in idx[nm]:
            idx[nm][d].sort()
    return idx


def _has_any_mark(rec: DayRecord) -> bool:
    return bool(rec.mark_up or rec.mark_down or rec.overtime_h or rec.night_h)


def check_presence(punch_idx: dict, table: AttendanceTable, mapper: NameMapper) -> list[Diff]:
    """规则组 A：到场核对。"""
    diffs: list[Diff] = []
    all_dates = set(table.dates())
    for name in sorted(table.days):
        punch_days = punch_idx.get(name, {})
        for d in sorted(all_dates):
            rec = table.days[name].get(d)
            if rec is None:
                continue
            punches = punch_days.get(d, [])
            has_punch = len(punches) > 0
            mark_present = _has_any_mark(rec)

            # A1: 有打卡但考勤表当天完全无任何记录 -> 漏记
            if has_punch and not mark_present:
                detail = "有打卡记录但考勤表未登记任何标记，疑似漏记"
                if punches[0].hour < 1:  # 凌晨打卡，可能属前一天加班下班卡
                    detail += "（打卡为凌晨时段，可能属前一日加班的下班卡）"
                diffs.append(Diff(
                    category="到场核对", name=name, on_date=d, level=LV_HARD,
                    raw_desc=f"打卡 {len(punches)} 次（{_fmt_time(punches[0])}~{_fmt_time(punches[-1])}）",
                    attend_desc="考勤表当天为空",
                    detail=detail,
                ))
                continue

            # A2: 无打卡但“上/下”行标了出勤√ -> 多记/代打卡嫌疑
            up_is_check = rec.mark_up == "√"
            down_is_check = rec.mark_down == "√"
            if (not has_punch) and (up_is_check or down_is_check):
                diffs.append(Diff(
                    category="到场核对", name=name, on_date=d, level=LV_HARD,
                    raw_desc="无打卡记录",
                    attend_desc=f"上={rec.mark_up or '-'} 下={rec.mark_down or '-'}",
                    detail="考勤表记了出勤√但设备无打卡，疑点多记或代打卡",
                ))

            # A3: 有加班小时但当天无打卡 -> 加班无打卡佐证
            if rec.overtime_h > 0 and not has_punch:
                diffs.append(Diff(
                    category="加班核对", name=name, on_date=d, level=LV_SUSPECT,
                    raw_desc="无打卡记录",
                    attend_desc=f"加={rec.overtime_h:g}H",
                    detail="考勤表记了加班但设备无打卡，需人工确认（可能人工补录）",
                ))

            # A4: 无打卡且标记为假期类 -> 待阶段二用 PDF 单据核对，本阶段仅提示
            if (not has_punch) and (rec.mark_up in _LEAVE_MARKS or rec.mark_down in _LEAVE_MARKS):
                diffs.append(Diff(
                    category="假单核对(待阶段二)", name=name, on_date=d, level=LV_SUSPECT,
                    raw_desc="无打卡记录",
                    attend_desc=f"上={rec.mark_up or '-'} 下={rec.mark_down or '-'}",
                    detail="标记了假期但无打卡，阶段二需与 PDF 请假单据核对",
                ))

            # A5: 当天仅有 1 次打卡 -> 缺一次卡（早退/晚到缺卡）
            if has_punch and len(punches) == 1:
                diffs.append(Diff(
                    category="缺卡提醒", name=name, on_date=d, level=LV_SUSPECT,
                    raw_desc=f"仅 1 次打卡（{_fmt_time(punches[0])}）",
                    attend_desc=f"上={rec.mark_up or '-'} 下={rec.mark_down or '-'}",
                    detail="当天只有一次打卡，疑似缺一次卡，请核对",
                ))
    return diffs


def check_totals(table: AttendanceTable) -> list[Diff]:
    """规则组 B：累计重算 —— 逐日标记求和 vs 月度累计列。

    计数口径（依据考勤表实际填写规律）：
    - 假别标记（補/年/病/事/培/差/其/曠）在“上”或“下”行出现一次 = 0.5 天（半天假）
    - 上/下行中的数字按星期归类：
        周六 → 週六、公眾假期上班（h)
        周日 → 休息日上班（h)
        其他工作日 → 待人工（可能为強制性假期等）
    """
    diffs: list[Diff] = []

    for name in sorted(table.days):
        tot = table.totals.get(name)
        if tot is None:
            continue
        # 逐日统计
        leave_cnt: dict[str, float] = defaultdict(float)  # 假别 -> 天数（0.5/标记）
        ot_sum = 0.0
        restday_sum = 0.0        # 周日数字
        weekend_holiday_sum = 0.0  # 周六数字
        other_workday_sum = 0.0  # 其他工作日数字
        night_sum = 0.0
        check_days = 0.0  # √ 出勤天数（上或下有√记 1 天）
        for d, rec in table.days[name].items():
            for mk in (rec.mark_up, rec.mark_down):
                if mk in _LEAVE_MARKS:
                    leave_cnt[mk] += 0.5  # 半天
            if rec.mark_up == "√" or rec.mark_down == "√":
                check_days += 1
            ot_sum += rec.overtime_h
            night_sum += rec.night_h
            val = rec.h_up + rec.h_down
            if val > 0:
                wd = d.weekday()  # 5=周六, 6=周日
                if wd == 5:
                    weekend_holiday_sum += val
                elif wd == 6:
                    restday_sum += val
                else:
                    other_workday_sum += val

        pairs = [
            ("培", leave_cnt["培"], tot.train_d, "培（d)"),
            ("差", leave_cnt["差"], tot.travel_d, "差（d)"),
            ("補", leave_cnt["補"], tot.comp_d, "補(d)"),
            ("年", leave_cnt["年"], tot.annual_d, "年（d)"),
            ("病", leave_cnt["病"], tot.sick_d, "病（d)"),
            ("事", leave_cnt["事"], tot.personal_d, "事（d)"),
            ("其", leave_cnt["其"], tot.other_d, "其（d)"),
            ("曠", leave_cnt["曠"], tot.absent_d, "曠（d)"),
            ("超時工作", ot_sum, tot.overtime_h, "超時工作（h)"),
            ("休息日上班", restday_sum, tot.restday_h, "休息日上班（h)"),
            ("週六公眾假期上班", weekend_holiday_sum, tot.weekend_holiday_h, "週六、公眾假期上班（h)"),
            ("夜間工作", night_sum, tot.night_h, "夜間工作（h)"),
        ]
        for label, calc, recorded, colname in pairs:
            if abs(calc - recorded) > 0.001:
                diffs.append(Diff(
                    category="累计重算", name=name, level=LV_HARD,
                    raw_desc=f"逐日求和={_num(calc)}",
                    attend_desc=f"月度累计[{colname}]={_num(recorded)}",
                    detail=f"“{colname}”列与逐日标记求和不一致，差值 {_num(calc - recorded)}",
                ))

        if other_workday_sum > 0:
            diffs.append(Diff(
                category="累计重算", name=name, level=LV_SUSPECT,
                raw_desc=f"工作日数字合计={_num(other_workday_sum)}",
                attend_desc="—",
                detail="上/下行在工作日出现数字（可能为強制性假期上班等），需人工确认归类",
            ))

        # 餐補計算 vs √ 天数（口径待确认，先作可疑项）
        if abs(check_days - tot.meal_count) > 0.001:
            diffs.append(Diff(
                category="餐補核對(口径待确认)", name=name, level=LV_SUSPECT,
                raw_desc=f"√ 出勤天数={_num(check_days)}",
                attend_desc=f"餐補計算={_num(tot.meal_count)}",
                detail="出勤(√)天数与餐補計算不一致；若餐補口径为出勤天数则为硬错误，请先确认口径",
            ))
    return diffs


def _fmt_time(t: datetime) -> str:
    return t.strftime("%H:%M")


def _num(v: float) -> str:
    return f"{v:g}"
