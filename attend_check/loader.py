# -*- coding: utf-8 -*-
"""数据加载与解析。

- load_raw(): 读取原始打卡记录表（每行一条打卡事件）
- load_attendance(): 解析手工考勤表主表（每人 4 行一组：上/下/加/夜間工作）
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date, datetime

from .name_map import to_simplified
from typing import Iterable

import openpyxl

# ============ 数据结构 ============

@dataclass
class Punch:
    emp_id: str
    name: str
    dept: str
    punch_time: datetime
    verify: str = ""


@dataclass
class DayRecord:
    """某员工某天在考勤表中的记录。"""

    mark_up: str = ""          # “上”行标记（√ / 補 / 年 / 病 / 事 / 培 / 差 / 曠 / 其 / 数字）
    mark_down: str = ""        # “下”行标记
    overtime_h: float = 0.0    # “加”行数值（超時工作小时）
    night_h: float = 0.0       # “夜間工作”行数值（小时）
    h_up: float = 0.0          # “上”行中的数字（如休息日上班小时）
    h_down: float = 0.0        # “下”行中的数字


@dataclass
class MonthTotals:
    """考勤表“月度累计”列（AJ~AW）的数值。"""

    name: str = ""
    train_d: float = 0.0      # 培（d)
    travel_d: float = 0.0     # 差（d)
    comp_d: float = 0.0       # 補(d)
    annual_d: float = 0.0     # 年（d)
    sick_d: float = 0.0       # 病（d)
    personal_d: float = 0.0   # 事（d)
    other_d: float = 0.0      # 其（d)
    absent_d: float = 0.0     # 曠（d)
    meal_count: float = 0.0   # 餐補計算
    overtime_h: float = 0.0   # 超時工作（h)
    restday_h: float = 0.0    # 休息日上班（h)
    weekend_holiday_h: float = 0.0  # 週六、公眾假期上班（h)
    mandatory_holiday_h: float = 0.0  # 強制性假期上班（h)
    night_h: float = 0.0      # 夜間工作（h)

    def as_dict(self) -> dict:
        return {
            "培": self.train_d, "差": self.travel_d, "補": self.comp_d,
            "年": self.annual_d, "病": self.sick_d, "事": self.personal_d,
            "其": self.other_d, "曠": self.absent_d, "餐補計算": self.meal_count,
            "超時工作": self.overtime_h, "休息日上班": self.restday_h,
            "週六公眾假期上班": self.weekend_holiday_h,
            "強制性假期上班": self.mandatory_holiday_h, "夜間工作": self.night_h,
        }


# ============ 加载原始打卡记录 ============

# 原始记录表各列的可能表头名称（简繁兼容，宽松匹配）
_RAW_COLUMN_ALIASES = {
    "emp_id":   ["工号", "工號", "员工编号", "員工編號", "编号", "編號", "工号/卡号", "工號/卡號"],
    "name":     ["姓名", "名字", "员工姓名", "員工姓名", "人员", "人員"],
    "dept":     ["部门", "部門", "科室", "单位", "單位", "所属部门", "所屬部門", "部门名称", "部門名稱"],
    "punch":    ["打卡时间", "打卡時間", "考勤时间", "考勤時間", "刷卡时间", "刷卡時間",
                 "时间", "時間", "打卡日期时间", "打卡日期時間", "考勤日期时间", "考勤日期時間"],
    "verify":   ["验证方式", "驗證方式", "验证", "驗證", "考勤方式", "打卡方式", "打卡方式"],
}


def _detect_raw_columns(header_row: tuple) -> dict[str, int]:
    """从表头行自动识别各列索引。返回 {字段名: 列索引}，找不到的字段为 -1。"""
    cols = {k: -1 for k in _RAW_COLUMN_ALIASES}
    for idx, cell in enumerate(header_row):
        if cell is None:
            continue
        text = str(cell).strip().replace(" ", "").replace("\u3000", "")
        if not text:
            continue
        for field, aliases in _RAW_COLUMN_ALIASES.items():
            if cols[field] >= 0:
                continue
            for alias in aliases:
                if alias in text or text in alias:
                    cols[field] = idx
                    break
    return cols


def _safe_get(row: tuple, idx: int, default=None):
    """安全取列，越界返回 default。"""
    if idx < 0 or idx >= len(row):
        return default
    return row[idx]


def load_raw(path: str) -> list[Punch]:
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    ws = wb.active
    punches: list[Punch] = []

    # 1. 扫描前 5 行找表头（含"姓名"和"打卡时间"类列名的行）
    col_map = None
    header_row_idx = 0
    rows_iter = list(ws.iter_rows(values_only=True))
    for i, row in enumerate(rows_iter[:10]):
        if not row:
            continue
        detected = _detect_raw_columns(row)
        if detected["name"] >= 0 and detected["punch"] >= 0:
            col_map = detected
            header_row_idx = i
            break

    # 兜底：如果没找到表头，用默认列索引（旧格式：A=工号 B=姓名 C=部门 G=打卡 H=验证）
    if col_map is None:
        col_map = {"emp_id": 0, "name": 1, "dept": 2, "punch": 6, "verify": 7}
        header_row_idx = 0

    # 2. 从表头下一行开始读数据
    for row in rows_iter[header_row_idx + 1:]:
        if not row:
            continue
        name = str(_safe_get(row, col_map["name"], "") or "").strip()
        if not name:
            continue
        emp_id = str(_safe_get(row, col_map["emp_id"], "") or "").strip()
        dept = str(_safe_get(row, col_map["dept"], "") or "").strip()
        punch_time = _safe_get(row, col_map["punch"])
        verify = str(_safe_get(row, col_map["verify"], "") or "")

        # 解析打卡时间（支持 datetime、字符串多种格式）
        if isinstance(punch_time, str):
            punch_time = _parse_datetime_str(punch_time)
        if not isinstance(punch_time, datetime):
            continue

        punches.append(Punch(emp_id=emp_id, name=name, dept=dept,
                             punch_time=punch_time, verify=verify))
    wb.close()
    return punches


def _parse_datetime_str(s: str):
    """尝试多种格式解析日期时间字符串，失败返回 None。"""
    s = s.strip()
    if not s:
        return None
    # ISO 格式
    try:
        return datetime.fromisoformat(s)
    except (ValueError, TypeError):
        pass
    # 常见格式
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S", "%Y-%m-%d %H:%M",
                "%Y/%m/%d %H:%M", "%Y-%m-%d", "%Y/%m/%d", "%Y年%m月%d日 %H:%M:%S",
                "%Y年%m月%d日 %H:%M", "%Y年%m月%d日"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


# ============ 加载手工考勤表 ============

# 考勤表结构（主表 考勤表721-820）：
#   R4 日期行：A=序號 B=日期 C=姓名, E..AI = 32 个日期列, AJ..AW = 月度累计
#   R5 星期行：E5..AI5 为 一~日
#   R7 起每个员工占 4 行：上 / 下 / 加 / 夜間工作
_MARK_LEAVE = {"培", "差", "補", "年", "病", "事", "其", "曠", "產", "喪", "婚"}


def _to_float(v) -> float:
    if v is None or v == "":
        return 0.0
    try:
        f = float(v)
        return 0.0 if f != f else f  # NaN -> 0
    except (TypeError, ValueError):
        return 0.0


class AttendanceTable:
    """解析后的考勤表。"""

    def __init__(self, period_start: date, period_end: date):
        self.period_start = period_start
        self.period_end = period_end
        self.date_cols: dict[int, date] = {}   # 列索引 -> 日期
        self.days: dict[str, dict[date, DayRecord]] = {}   # 姓名 -> {日期: DayRecord}
        self.totals: dict[str, MonthTotals] = {}           # 姓名 -> 月度累计
        self.extra_rows: list[str] = []                    # 表尾非员工行（备注等）

    def dates(self) -> list[date]:
        return [self.date_cols[c] for c in sorted(self.date_cols)]


def _is_person_row(name: str) -> bool:
    """过滤表尾的 備註/考勤員 等非员工行（简繁兼容）。"""
    if not name:
        return False
    if any(k in name for k in ("備註", "备注", "考勤員", "考勤员", "部門負責", "部门负责",
                                "主管領導", "主管领导", "：", ":")):
        return False
    return len(name) <= 4  # 姓名通常 2~4 字


def load_attendance(path: str, sheet_name: str,
                    period_start: date, period_end: date,
                    name_normalize=None) -> AttendanceTable:
    """解析手工考勤表主表。

    name_normalize: 可选的姓名归一化函数（如 NameMapper.normalize），
    用于把考勤表的繁体姓名统一为简体，与原始打卡记录配对。
    """
    # 考勤表较小（约 150 行），用普通模式加载以支持高效的 ws.cell() 随机访问
    wb = openpyxl.load_workbook(path, data_only=True, read_only=False)
    ws = wb[sheet_name]
    if name_normalize is None:
        name_normalize = lambda s: s
    table = AttendanceTable(period_start, period_end)

    # 1. 定位表头（含"序號/序号"和日期序列的行）
    header_row = None
    date_cols: dict[int, date] = {}
    for r in range(1, min(ws.max_row, 12) + 1):
        vals = [c.value for c in ws[r]]
        if any(v in ("序號", "序号") for v in vals):
            header_row = r
            for ci, v in enumerate(vals):
                if isinstance(v, datetime):
                    d = v.date()
                elif isinstance(v, date):
                    d = v
                else:
                    continue
                if period_start <= d <= period_end:
                    date_cols[ci] = d
            break
    if header_row is None or not date_cols:
        raise ValueError(f"未在 {sheet_name} 找到日期表头，请检查表结构")
    table.date_cols = date_cols

    # 2. 定位"月度累计"起始列（表头行中值为"月度累计/月度纍計"的列）
    hdr = [c.value for c in ws[header_row]]
    total_start = None
    for ci, v in enumerate(hdr):
        if v in ("月度累计", "月度纍計"):
            total_start = ci
            break
    if total_start is None:
        raise ValueError("未找到“月度累计”列")

    # 3. 逐员工块解析（4 行一组：上/下/加/夜間工作）
    # R7 为员工区表头（姓名/假期），R9 起为第一个员工块
    r = header_row + 5
    max_row = ws.max_row
    col_b, col_c = 2, 3  # openpyxl 列索引 1-based：B 列=2，C 列=3
    while r <= max_row:
        b_name = ws.cell(row=r, column=col_b).value
        c_label = ws.cell(row=r, column=col_c).value
        if not _is_person_row(str(b_name or "").strip()):
            # 非员工行（表尾备注/签名区等），逐行跳过
            raw = str(b_name or "").strip()
            if raw:
                table.extra_rows.append(raw)
            r += 1
            continue
        if str(c_label or "").strip() != "上":
            # 结构异常，跳过该行避免死循环
            r += 1
            continue
        name = str(b_name).strip()
        name = name_normalize(name)  # 姓名统一简体，便于与原始记录配对

        block = {}
        for k in range(4):
            block[k] = [ws.cell(row=r + k, column=ci + 1).value for ci in sorted(date_cols)]

        day_map: dict[date, DayRecord] = {}
        for pos, d in enumerate(sorted(date_cols.items(), key=lambda kv: kv[1])):
            ci, dt = d
            rec = DayRecord()
            v_up = block[0][pos]
            v_down = block[1][pos]
            v_ot = block[2][pos]
            v_night = block[3][pos]
            rec.mark_up = "" if v_up is None else to_simplified(str(v_up).strip())
            rec.mark_down = "" if v_down is None else to_simplified(str(v_down).strip())
            rec.overtime_h = _to_float(v_ot)
            rec.night_h = _to_float(v_night)
            rec.h_up = _to_float(v_up) if isinstance(v_up, (int, float)) else 0.0
            rec.h_down = _to_float(v_down) if isinstance(v_down, (int, float)) else 0.0
            day_map[dt] = rec
        table.days[name] = day_map

        # 月度累计列
        tot = MonthTotals(name=name)
        fields = [
            ("train_d", 0), ("travel_d", 1), ("comp_d", 2), ("annual_d", 3),
            ("sick_d", 4), ("personal_d", 5), ("other_d", 6), ("absent_d", 7),
            ("meal_count", 8), ("overtime_h", 9), ("restday_h", 10),
            ("weekend_holiday_h", 11), ("mandatory_holiday_h", 12), ("night_h", 13),
        ]
        for fname, off in fields:
            v = ws.cell(row=r, column=total_start + off + 1).value  # total_start 为 0-based，转 1-based
            setattr(tot, fname, _to_float(v))
        table.totals[name] = tot

        r += 4

    wb.close()
    return table
