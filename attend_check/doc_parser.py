# -*- coding: utf-8 -*-
"""单据解析模块。

从 OCR 结果中识别单据类型（请假单/休假单/加班单/司机加班单），
提取姓名、日期、时长等关键字段。打印体单据自动解析，手写单据提取可识别部分。
"""
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from .pdf_ocr import OcrPage, OcrLine
from .name_map import to_simplified


# 单据类型标识关键词（宽松匹配，容忍 OCR 错字和截断）
DOC_TYPE_KEYWORDS = {
    "leave_application": ["假期申", "请假申", "假期申請", "请假申請"],
    "vacation_application": ["休假申", "休假申請", "員工休假", "员工休假"],
    "overtime_application": ["加班申", "加班申請", "加班申请"],
    "driver_overtime": ["司机加班", "司機加班"],
    "sick_certificate": ["疾病诊断", "诊断证明", "诊断證明", "人民医院", "医院"],
    "overtime_agreement": ["超时工作協", "超时工作协", "超時工作協", "工作時间協", "工作时间协"],
}

# 考勤表页强特征词（出现则判定为考勤表扫描页，非单据）
ATTEND_SHEET_FEATURES = ["月度累计", "月度纍計", "餐補", "餐补", "夜間工作", "夜间工作",
                         "夜固工作", "夜周工作", "考勤記表", "考勤记表", "员工考勤記"]

# 假期类型关键词
LEAVE_TYPE_KEYWORDS = {
    "annual": ["年假", "年休假"],
    "compensatory": ["补偿假", "補償假", "补休", "補休", "调休", "調休"],
    "sick": ["病假"],
    "personal": ["事假"],
    "maternity": ["产假", "產假"],
    "bereavement": ["丧假", "喪假"],
    "marriage": ["婚假"],
    "training": ["培训", "培訓"],
    "business_trip": ["出差"],
    "other": ["其他假", "其他假期"],
}


@dataclass
class DocumentRecord:
    """解析后的单据记录。"""
    page_num: int
    doc_type: str  # leave_application / vacation_application / overtime_application / driver_overtime
    doc_type_label: str  # 中文标签
    employee_name: Optional[str] = None
    department: Optional[str] = None
    leave_type: Optional[str] = None  # 假期类型（仅请假/休假单）
    leave_type_label: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    days: Optional[float] = None  # 请假天数
    overtime_date: Optional[date] = None  # 加班日期（加班单）
    overtime_start: Optional[str] = None  # 加班开始时间
    overtime_end: Optional[str] = None  # 加班结束时间
    overtime_hours: Optional[float] = None  # 加班时长
    overtime_items: list = field(default_factory=list)  # 司机加班单的多条记录
    raw_text: str = ""  # OCR 全文（供人工复核）
    confidence: str = "high"  # high / medium / low（low 表示手写多、需人工复核）
    notes: str = ""  # 备注


def _normalize_text(text: str) -> str:
    """归一化 OCR 文本：简繁统一、去空格。"""
    return to_simplified(text.replace(" ", "").replace("\u3000", ""))


def _find_line(page: OcrPage, keyword: str) -> Optional[OcrLine]:
    """在页面中查找包含关键词的行。"""
    nk = _normalize_text(keyword)
    for line in page.lines:
        if nk in _normalize_text(line.text):
            return line
    return None


def _detect_doc_type(page: OcrPage) -> tuple[str, str]:
    """识别单据类型。返回 (type_key, 中文标签)。"""
    full = _normalize_text(page.full_text)

    # 先判断是否为考勤表扫描页（非单据）
    for feat in ATTEND_SHEET_FEATURES:
        if _normalize_text(feat) in full:
            return "attendance_sheet", "考勤表页"

    for doc_type, keywords in DOC_TYPE_KEYWORDS.items():
        for kw in keywords:
            if _normalize_text(kw) in full:
                labels = {
                    "leave_application": "请假申请单",
                    "vacation_application": "员工休假申请单",
                    "overtime_application": "加班申请单",
                    "driver_overtime": "司机加班单",
                    "sick_certificate": "病假证明",
                    "overtime_agreement": "超时工作协议书",
                }
                return doc_type, labels[doc_type]
    return "unknown", "未知单据"


def _detect_leave_type(page: OcrPage) -> tuple[Optional[str], Optional[str]]:
    """识别假期类型。"""
    full = _normalize_text(page.full_text)
    for lt, keywords in LEAVE_TYPE_KEYWORDS.items():
        for kw in keywords:
            if _normalize_text(kw) in full:
                labels = {
                    "annual": "年假", "compensatory": "补偿假", "sick": "病假",
                    "personal": "事假", "maternity": "产假", "bereavement": "丧假",
                    "marriage": "婚假", "training": "培训", "business_trip": "出差",
                    "other": "其他假",
                }
                return lt, labels[lt]
    return None, None


_DATE_PATTERNS = [
    # 2026/8/20 或 2026-08-20 或 2026年8月20日
    r"(20\d{2})[/\-.年](\d{1,2})[/\-.月](\d{1,2})",
    # 8月20日（无年份，默认2026）
    r"(\d{1,2})月(\d{1,2})日",
]


def _extract_dates(text: str) -> list[date]:
    """从文本中提取所有日期。"""
    dates = []
    for pat in _DATE_PATTERNS:
        for m in re.finditer(pat, text):
            groups = m.groups()
            if len(groups) == 3:
                y, mo, d = int(groups[0]), int(groups[1]), int(groups[2])
            else:
                y, mo, d = 2026, int(groups[0]), int(groups[1])
            try:
                dates.append(date(y, mo, d))
            except ValueError:
                pass
    # 去重保序
    seen = set()
    unique = []
    for d in dates:
        if d not in seen:
            seen.add(d)
            unique.append(d)
    return unique


def _extract_time_range(text: str) -> tuple[Optional[str], Optional[str], Optional[float]]:
    """提取时间范围如 18:30-21:30，返回 (start, end, hours)。"""
    m = re.search(r"(\d{1,2}):(\d{2})\s*[-~至]\s*(\d{1,2}):(\d{2})", text)
    if m:
        sh, sm, eh, em = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
        start = f"{sh:02d}:{sm:02d}"
        end = f"{eh:02d}:{em:02d}"
        hours = (eh * 60 + em - sh * 60 - sm) / 60.0
        if hours < 0:
            hours += 24  # 跨天
        return start, end, round(hours, 2)
    return None, None, None


def _extract_number_after(text: str, keyword: str) -> Optional[float]:
    """提取关键词后的数字（如"加班时数 3"）。"""
    nk = _normalize_text(keyword)
    nt = _normalize_text(text)
    idx = nt.find(nk)
    if idx >= 0:
        after = nt[idx + len(nk):idx + len(nk) + 20]
        m = re.search(r"(\d+\.?\d*)", after)
        if m:
            return float(m.group(1))
    return None


# 常见字段名，不作为姓名候选
_NAME_EXCLUDE = {
    "加班日期", "加班时间", "加班时数", "申请加班", "加班内容", "加班申请",
    "部门负责", "部门负责", "考勤员签", "申请人签", "项目副总", "项目总经",
    "休假类别", "休假起止", "部门负责", "公司主管", "休假期间", "注意事项",
    "填表日期", "普通员工", "员工适用", "司机姓名", "用车人签", "合计时间",
    "加班申", "申请时", "批示时", "签收时", "领导签",
}


def _find_name_from_lines(page: OcrPage, name_pool: list[str]) -> Optional[str]:
    """从已知员工名单中匹配 OCR 识别出的姓名。"""
    candidates = []
    for line in page.lines:
        t = _normalize_text(line.text)
        # 排除字段名和过长/过短文本
        if 2 <= len(t) <= 4 and re.match(r"^[\u4e00-\u9fff]+$", t):
            if any(ex in t for ex in _NAME_EXCLUDE):
                continue
            candidates.append((t, line.conf))
    # 与员工名单匹配（先精确匹配候选，再从长文本中查找）
    for name in name_pool:
        ns = _normalize_text(name)
        for cand, conf in candidates:
            if cand == ns or cand in ns or ns in cand:
                return name
    # 从长文本行（标题等）中查找姓名
    for line in page.lines:
        t = _normalize_text(line.text)
        for name in name_pool:
            ns = _normalize_text(name)
            if ns in t and len(ns) >= 2:
                return name
    # 无名单时返回置信度最高的候选
    if candidates:
        candidates.sort(key=lambda x: -x[1])
        return candidates[0][0]
    return None


def _extract_date_after_keyword(page: OcrPage, keyword: str, max_after: int = 6) -> Optional[date]:
    """在指定关键词行之后（含同行）查找第一个日期。

    用于从"加班日期"、"休假起止日期"等字段后提取实际日期，
    避免把表头的考勤周期（如7月21日-8月20日）误当作业务日期。
    """
    nk = _normalize_text(keyword)
    # 按 y 坐标排序（阅读顺序）
    sorted_lines = sorted(page.lines, key=lambda l: (round(l.y / 15), l.x))
    for i, line in enumerate(sorted_lines):
        if nk in _normalize_text(line.text):
            # 1) 同行内可能包含日期（如"加班日期 2026/7/23"）
            dates_in_line = _extract_dates(line.text)
            if dates_in_line:
                return dates_in_line[0]
            # 2) 后续 max_after 行内查找
            for j in range(i + 1, min(i + 1 + max_after, len(sorted_lines))):
                dates = _extract_dates(sorted_lines[j].text)
                if dates:
                    return dates[0]
            break
    return None


def parse_page(page: OcrPage, name_pool: Optional[list[str]] = None) -> DocumentRecord:
    """解析单页 OCR 结果为单据记录。"""
    doc_type, doc_label = _detect_doc_type(page)
    full_text = page.full_text
    rec = DocumentRecord(
        page_num=page.page_num,
        doc_type=doc_type,
        doc_type_label=doc_label,
        raw_text=full_text,
    )

    if doc_type == "attendance_sheet":
        rec.confidence = "high"
        rec.notes = "考勤表扫描页，非单据"
        return rec

    if name_pool:
        rec.employee_name = _find_name_from_lines(page, name_pool)

    # 提取日期
    all_dates = _extract_dates(full_text)

    if doc_type in ("leave_application", "vacation_application"):
        # 请假/休假单
        rec.leave_type, rec.leave_type_label = _detect_leave_type(page)
        # 优先从"休假起止日期"字段后提取，避免误取表头周期
        leave_dates = []
        kw_date = _extract_date_after_keyword(page, "休假起止日期", max_after=4)
        if kw_date:
            leave_dates.append(kw_date)
        # 也从全文提取，排除考勤周期日期
        period_start = date(2026, 7, 21)
        period_end = date(2026, 8, 20)
        for d in all_dates:
            if d not in (period_start, period_end) and d not in leave_dates:
                if date(2026, 7, 1) <= d <= date(2026, 9, 30):
                    leave_dates.append(d)
        if len(leave_dates) >= 2:
            rec.start_date = leave_dates[0]
            rec.end_date = leave_dates[-1]
            if rec.end_date < rec.start_date:
                rec.start_date, rec.end_date = rec.end_date, rec.start_date
            rec.days = (rec.end_date - rec.start_date).days + 1
        elif len(leave_dates) == 1:
            rec.start_date = rec.end_date = leave_dates[0]
            rec.days = 1
        # 休假申请单多为手写，置信度低
        if doc_type == "vacation_application":
            rec.confidence = "low"
            rec.notes = "手写单据，关键字段需人工复核"
        else:
            rec.confidence = "medium"

    elif doc_type == "overtime_application":
        # 加班申请单（打印体，解析度高）
        rec.confidence = "high"
        # 加班日期在"加班日期"字段后，不是表头的考勤周期
        ot_date = _extract_date_after_keyword(page, "加班日期")
        if ot_date:
            rec.overtime_date = ot_date
        elif all_dates:
            # 回退：排除考勤周期（7/21、8/20）后取第一个
            period_start = date(2026, 7, 21)
            period_end = date(2026, 8, 20)
            filtered = [d for d in all_dates if d not in (period_start, period_end)]
            if filtered:
                rec.overtime_date = filtered[0]
            elif all_dates:
                rec.overtime_date = all_dates[0]
        # 提取加班时间和时数
        start, end, hours = _extract_time_range(full_text)
        rec.overtime_start = start
        rec.overtime_end = end
        if hours:
            rec.overtime_hours = hours
        else:
            rec.overtime_hours = _extract_number_after(full_text, "加班时数")

    elif doc_type == "driver_overtime":
        # 司机加班单（全手写表格）
        rec.confidence = "low"
        rec.notes = "手写表格，需人工复核逐条加班记录"
        # 尝试提取合计时间
        total = _extract_number_after(full_text, "合计时间")
        if total:
            rec.overtime_hours = total
        # 提取所有日期作为加班日期列表
        period_dates = [d for d in all_dates
                        if date(2026, 7, 1) <= d <= date(2026, 9, 30)]
        if period_dates:
            rec.overtime_date = period_dates[0]
            rec.overtime_items = [{"date": d} for d in period_dates]

    else:
        rec.confidence = "low"
        rec.notes = "未能识别单据类型，需人工复核"

    return rec


def parse_all(pages: list[OcrPage], name_pool: Optional[list[str]] = None) -> list[DocumentRecord]:
    """解析全部页。"""
    return [parse_page(p, name_pool) for p in pages]
