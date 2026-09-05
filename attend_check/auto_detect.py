# -*- coding: utf-8 -*-
"""自动检测模块：扫描目录，识别源文件并推断考勤周期。

支持随意命名：先按文件名关键词识别，识别不出来时读取文件内容判断。
识别优先级：config.json 显式配置 > 文件名关键词 > 文件内容特征。
"""
import os
import re
from datetime import date, datetime
from typing import Optional


def _list_files(directory: str, ext: str) -> list[str]:
    """列出目录下指定扩展名的文件（按修改时间倒序），排除 Office 临时文件。"""
    files = []
    for f in os.listdir(directory):
        if f.lower().endswith(ext.lower()) and not f.startswith("~$"):
            full = os.path.join(directory, f)
            if os.path.isfile(full):
                files.append(f)
    files.sort(key=lambda f: os.path.getmtime(os.path.join(directory, f)), reverse=True)
    return files


def _is_raw_punch_file(path: str) -> bool:
    """通过内容判断是否为原始打卡记录（含打卡时间列）。"""
    try:
        import openpyxl
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        ws = wb[wb.sheetnames[0]]
        # 读前 5 行，找表头
        for row in ws.iter_rows(min_row=1, max_row=5, values_only=True):
            for cell in row:
                if cell and isinstance(cell, str):
                    if "打卡" in cell or "考勤时间" in cell or "验证方式" in cell:
                        wb.close()
                        return True
        wb.close()
    except Exception:
        pass
    return False


def _is_attendance_sheet(path: str) -> bool:
    """通过内容判断是否为手工考勤表（含上/下/加/夜間工作行标签，简繁兼容）。"""
    try:
        import openpyxl
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        labels = {"上", "下", "加", "夜間工作", "夜间工作", "夜間", "夜间"}
        for sheet_name in wb.sheetnames:
            ws = wb[sheet_name]
            # 读前 30 行的 B/C 列（姓名/标签列）
            for row in ws.iter_rows(min_row=1, max_row=30, min_col=2, max_col=3, values_only=True):
                for cell in row:
                    if cell and isinstance(cell, str) and cell.strip() in labels:
                        wb.close()
                        return True
        wb.close()
    except Exception:
        pass
    return False


def _extract_period_from_raw(path: str) -> Optional[tuple[date, date]]:
    """从原始打卡记录的打卡时间列提取周期（最早~最晚日期）。"""
    try:
        import openpyxl
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        ws = wb[wb.sheetnames[0]]
        dates = []
        for row in ws.iter_rows(min_row=2, values_only=True):
            for cell in row:
                if isinstance(cell, datetime):
                    dates.append(cell.date())
                elif isinstance(cell, date):
                    dates.append(cell)
        wb.close()
        if dates:
            return min(dates), max(dates)
    except Exception:
        pass
    return None


def _extract_period_from_attendance(path: str) -> Optional[tuple[date, date]]:
    """从考勤表的日期表头提取周期。"""
    try:
        import openpyxl
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        for sheet_name in wb.sheetnames:
            ws = wb[sheet_name]
            # 找"序號"行，其后的日期列
            for row in ws.iter_rows(min_row=1, max_row=10, values_only=True):
                dates = []
                for cell in row:
                    if isinstance(cell, datetime):
                        dates.append(cell.date())
                    elif isinstance(cell, date):
                        dates.append(cell)
                if len(dates) >= 5:  # 日期表头行通常有很多日期
                    wb.close()
                    return min(dates), max(dates)
        wb.close()
    except Exception:
        pass
    return None


def detect_raw_file(directory: str) -> Optional[str]:
    """识别原始打卡记录 xlsx（先文件名，后内容）。"""
    xlsx_files = _list_files(directory, ".xlsx")
    # 1. 文件名关键词
    for f in xlsx_files:
        if "原始记录" in f or "打卡记录" in f or "打卡" in f or "raw" in f.lower() or "punch" in f.lower():
            return f
    # 2. 内容判断
    for f in xlsx_files:
        if _is_raw_punch_file(os.path.join(directory, f)):
            return f
    return None


def detect_attend_file(directory: str, raw_file: Optional[str] = None) -> Optional[str]:
    """识别手工考勤表 xlsx（先文件名，后内容）。"""
    xlsx_files = _list_files(directory, ".xlsx")
    # 排除原始记录和报告
    candidates = [f for f in xlsx_files if f != raw_file
                  and "差异报告" not in f and "对账" not in f]
    # 1. 文件名关键词
    for f in candidates:
        if "考勤" in f or "attend" in f.lower() or "roster" in f.lower():
            return f
    # 2. 内容判断
    for f in candidates:
        if _is_attendance_sheet(os.path.join(directory, f)):
            return f
    # 3. 兜底：取第一个非原始记录的 xlsx
    if candidates:
        return candidates[0]
    return None


def detect_pdf_file(directory: str) -> Optional[str]:
    """识别 PDF 单据文件（取最新的一个）。"""
    pdfs = _list_files(directory, ".pdf")
    return pdfs[0] if pdfs else None


def detect_attend_sheet(attend_path: str) -> Optional[str]:
    """从考勤表 xlsx 中识别 sheet 名（取含'考勤'的，或第一个含日期表头的）。"""
    try:
        import openpyxl
        wb = openpyxl.load_workbook(attend_path, read_only=True)
        sheets = wb.sheetnames
        wb.close()
        for s in sheets:
            if "考勤" in s:
                return s
        return sheets[0] if sheets else None
    except Exception:
        return None


def extract_period_from_filename(filename: str) -> Optional[tuple[date, date]]:
    """从文件名中提取考勤周期。"""
    # 模式1：8位日期-8位日期，如 20260721-20260820
    m = re.search(r"(\d{4})(\d{2})(\d{2})[-_~至到]+(\d{4})(\d{2})(\d{2})", filename)
    if m:
        start = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        end = date(int(m.group(4)), int(m.group(5)), int(m.group(6)))
        return start, end
    # 模式2：括号内 8位-8位
    m = re.search(r"[（(](\d{8})[-_~至到]+(\d{8})[）)]", filename)
    if m:
        s, e = m.group(1), m.group(2)
        return (date(int(s[:4]), int(s[4:6]), int(s[6:8])),
                date(int(e[:4]), int(e[4:6]), int(e[6:8])))
    # 模式3：月日-月日（短格式，如 721-820）
    m = re.search(r"(?<!\d)(\d{1,2})(\d{2})[-_~至到]+(\d{1,2})(\d{2})(?!\d)", filename)
    if m:
        year = datetime.now().year
        sm, sd, em, ed = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
        end_year = year if em >= sm else year + 1
        try:
            return date(year, sm, sd), date(end_year, em, ed)
        except ValueError:
            pass
    return None


def auto_detect(directory: str) -> dict:
    """自动检测所有源文件和考勤周期。

    识别顺序：文件名关键词 → 文件内容特征。
    周期提取顺序：文件名 → 原始记录打卡时间 → 考勤表日期表头。
    """
    result = {
        "raw_file": None,
        "attend_file": None,
        "attend_sheet": None,
        "pdf_file": None,
        "period_start": None,
        "period_end": None,
    }

    result["raw_file"] = detect_raw_file(directory)
    result["attend_file"] = detect_attend_file(directory, result["raw_file"])
    result["pdf_file"] = detect_pdf_file(directory)

    # 周期提取：1.文件名 2.原始记录内容 3.考勤表内容
    if result["raw_file"]:
        period = extract_period_from_filename(result["raw_file"])
        if not period:
            period = _extract_period_from_raw(os.path.join(directory, result["raw_file"]))
        if period:
            result["period_start"], result["period_end"] = period

    if not result["period_start"] and result["attend_file"]:
        period = extract_period_from_filename(result["attend_file"])
        if not period:
            period = _extract_period_from_attendance(os.path.join(directory, result["attend_file"]))
        if period:
            result["period_start"], result["period_end"] = period

    # 识别考勤表 sheet 名
    if result["attend_file"]:
        result["attend_sheet"] = detect_attend_sheet(
            os.path.join(directory, result["attend_file"]))

    return result
