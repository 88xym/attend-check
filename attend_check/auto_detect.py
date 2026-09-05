# -*- coding: utf-8 -*-
"""自动检测模块：扫描目录，识别源文件并推断考勤周期。

用户无需手动修改 config.json，只需将三个源文件放入项目目录即可。
识别优先级：config.json 中显式配置的路径 > 自动扫描。
"""
import os
import re
from datetime import date
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


def detect_raw_file(directory: str) -> Optional[str]:
    """识别原始打卡记录 xlsx。"""
    for f in _list_files(directory, ".xlsx"):
        name = f.lower()
        if "原始记录" in f or "打卡记录" in f or "raw" in name or "punch" in name:
            return f
    return None


def detect_attend_file(directory: str) -> Optional[str]:
    """识别手工考勤表 xlsx（排除原始记录和差异报告）。"""
    for f in _list_files(directory, ".xlsx"):
        name = f.lower()
        if "原始记录" in f or "打卡记录" in f or "差异报告" in f or "对账" in f:
            continue
        if "考勤" in f or "attend" in name or "roster" in name:
            return f
    # 兜底：取第一个非原始记录的 xlsx
    for f in _list_files(directory, ".xlsx"):
        if "原始记录" not in f and "差异报告" not in f and "对账" not in f:
            return f
    return None


def detect_pdf_file(directory: str) -> Optional[str]:
    """识别 PDF 单据文件（取最新的一个）。"""
    pdfs = _list_files(directory, ".pdf")
    return pdfs[0] if pdfs else None


def detect_attend_sheet(attend_path: str) -> Optional[str]:
    """从考勤表 xlsx 中识别 sheet 名（取含'考勤'的，或第一个）。"""
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
    """从文件名中提取考勤周期。

    支持格式：
    - 原始记录表(20260721-20260820).xlsx → 2026-07-21 ~ 2026-08-20
    - 721-820机场项目考勤.xlsx → 需结合年份推断
    - 考勤表_202607_202608.xlsx
    """
    # 模式1：8位日期-8位日期，如 20260721-20260820
    m = re.search(r"(\d{4})(\d{2})(\d{2})[-_~至到]+(\d{4})(\d{2})(\d{2})", filename)
    if m:
        start = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        end = date(int(m.group(4)), int(m.group(5)), int(m.group(6)))
        return start, end

    # 模式2：括号内 8位-8位，如 (20260721-20260820)
    m = re.search(r"[（(](\d{8})[-_~至到]+(\d{8})[）)]", filename)
    if m:
        s, e = m.group(1), m.group(2)
        start = date(int(s[:4]), int(s[4:6]), int(s[6:8]))
        end = date(int(e[:4]), int(e[4:6]), int(e[6:8]))
        return start, end

    # 模式3：月日-月日（短格式，如 721-820），需推断年份
    m = re.search(r"(?<!\d)(\d{1,2})(\d{2})[-_~至到]+(\d{1,2})(\d{2})(?!\d)", filename)
    if m:
        from datetime import datetime
        year = datetime.now().year
        # 如果结束月份小于开始月份，说明跨年
        sm, sd, em, ed = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
        start_year = year
        end_year = year if em >= sm else year + 1
        try:
            start = date(start_year, sm, sd)
            end = date(end_year, em, ed)
            return start, end
        except ValueError:
            pass

    return None


def auto_detect(directory: str) -> dict:
    """自动检测所有源文件和考勤周期。

    返回 dict，可直接合并到 config 中。
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
    result["attend_file"] = detect_attend_file(directory)
    result["pdf_file"] = detect_pdf_file(directory)

    # 从原始记录文件名提取周期（最可靠）
    if result["raw_file"]:
        period = extract_period_from_filename(result["raw_file"])
        if period:
            result["period_start"], result["period_end"] = period

    # 从考勤表文件名提取周期（兜底）
    if not result["period_start"] and result["attend_file"]:
        period = extract_period_from_filename(result["attend_file"])
        if period:
            result["period_start"], result["period_end"] = period

    # 识别考勤表 sheet 名
    if result["attend_file"]:
        attend_path = os.path.join(directory, result["attend_file"])
        result["attend_sheet"] = detect_attend_sheet(attend_path)

    return result
