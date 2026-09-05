# -*- coding: utf-8 -*-
"""单据核对模块（阶段二）。

将 PDF 解析出的请假单/加班单与考勤表标记进行三方核对。
策略：
- 高/中置信度单据（打印体）：自动核对，有差异报可疑项
- 低置信度单据（手写体）：仅列清单，不做自动差异核对（避免 OCR 误报）
- 考勤表缺单据核对：仅针对高置信度单据覆盖的人员
"""
from dataclasses import dataclass
from datetime import date
from typing import Optional

from .doc_parser import DocumentRecord
from .loader import AttendanceTable
from .rules import Diff, LV_HARD, LV_SUSPECT
from .name_map import NameMapper


LEAVE_TYPE_TO_MARK = {
    "annual": "年", "compensatory": "补", "sick": "病", "personal": "事",
    "maternity": "其", "bereavement": "其", "marriage": "其",
    "training": "培", "business_trip": "差", "other": "其",
}

LEAVE_MARKS = {"年", "补", "病", "事", "其", "培", "差"}


@dataclass
class DocReconcileResult:
    diffs: list
    docs_total: int
    docs_matched: int
    docs_unmatched: int
    docs_manual_review: int  # 低置信度需人工复核
    attendance_leave_without_doc: int
    attendance_overtime_without_doc: int


def _date_range(start: date, end: date) -> list[date]:
    if start > end:
        start, end = end, start
    days = (end - start).days + 1
    return [date.fromordinal(start.toordinal() + i) for i in range(days)]


def reconcile_docs(
    docs: list[DocumentRecord],
    table: AttendanceTable,
    mapper: NameMapper,
) -> DocReconcileResult:
    diffs: list[Diff] = []

    # 只对高/中置信度单据建索引（用于核对）
    leave_docs: dict[str, dict[date, list[DocumentRecord]]] = {}
    overtime_docs: dict[str, dict[date, list[DocumentRecord]]] = {}
    docs_with_name = 0
    docs_manual_review = 0

    for doc in docs:
        if doc.doc_type in ("attendance_sheet", "overtime_agreement", "unknown"):
            continue
        if not doc.employee_name:
            if doc.confidence == "low":
                docs_manual_review += 1
            continue
        name = mapper.normalize(doc.employee_name)
        docs_with_name += 1

        # 低置信度单据不参与自动核对
        if doc.confidence == "low":
            docs_manual_review += 1
            continue

        if doc.doc_type in ("leave_application", "vacation_application", "sick_certificate"):
            if doc.start_date and doc.end_date:
                for d in _date_range(doc.start_date, doc.end_date):
                    leave_docs.setdefault(name, {}).setdefault(d, []).append(doc)
            elif doc.start_date:
                leave_docs.setdefault(name, {}).setdefault(doc.start_date, []).append(doc)
        elif doc.doc_type in ("overtime_application",):
            if doc.overtime_date:
                overtime_docs.setdefault(name, {}).setdefault(doc.overtime_date, []).append(doc)

    docs_matched = 0
    docs_unmatched = 0

    # 1. 检查每张高/中置信度单据是否在考勤表中有对应记录
    for doc in docs:
        if doc.doc_type in ("attendance_sheet", "overtime_agreement", "unknown"):
            continue
        if doc.confidence == "low" or not doc.employee_name:
            continue
        name = mapper.normalize(doc.employee_name)
        if name not in table.days:
            docs_unmatched += 1
            diffs.append(Diff(
                category="单据核对", name=name, level=LV_SUSPECT,
                raw_desc=f"PDF第{doc.page_num}页 {doc.doc_type_label}",
                attend_desc="考勤表无此员工",
                detail=f"单据上的员工'{name}'不在考勤表中（可能别名/简繁问题，或非本周期人员）",
            ))
            continue

        matched = False
        if doc.doc_type in ("leave_application", "vacation_application", "sick_certificate"):
            check_dates = []
            if doc.start_date and doc.end_date:
                check_dates = _date_range(doc.start_date, doc.end_date)
            elif doc.start_date:
                check_dates = [doc.start_date]
            for d in check_dates:
                rec = table.days[name].get(d)
                if rec and (rec.mark_up in LEAVE_MARKS or rec.mark_down in LEAVE_MARKS):
                    matched = True
                    break
            if not matched:
                docs_unmatched += 1
                date_str = f"{doc.start_date}~{doc.end_date}" if doc.start_date else "日期未识别"
                diffs.append(Diff(
                    category="单据核对", name=name, on_date=doc.start_date, level=LV_SUSPECT,
                    raw_desc=f"PDF第{doc.page_num}页 {doc.doc_type_label}（{doc.leave_type_label or '假期'}，{date_str}）",
                    attend_desc="考勤表对应日期无假单标记",
                    detail=f"有{doc.leave_type_label or '请假'}单据但考勤表未登记假单标记（置信度:{doc.confidence}）",
                ))
            else:
                docs_matched += 1

        elif doc.doc_type == "overtime_application":
            if doc.overtime_date:
                rec = table.days[name].get(doc.overtime_date)
                if rec and rec.overtime_h > 0:
                    matched = True
                    if doc.overtime_hours and abs(rec.overtime_h - doc.overtime_hours) > 0.5:
                        diffs.append(Diff(
                            category="单据核对", name=name, on_date=doc.overtime_date, level=LV_SUSPECT,
                            raw_desc=f"PDF第{doc.page_num}页 加班单（{doc.overtime_hours}H）",
                            attend_desc=f"考勤表加班={rec.overtime_h:g}H",
                            detail=f"加班时数不一致：单据{doc.overtime_hours}H vs 考勤表{rec.overtime_h:g}H",
                        ))
            if not matched:
                docs_unmatched += 1
                date_str = str(doc.overtime_date) if doc.overtime_date else "日期未识别"
                diffs.append(Diff(
                    category="单据核对", name=name, on_date=doc.overtime_date, level=LV_SUSPECT,
                    raw_desc=f"PDF第{doc.page_num}页 {doc.doc_type_label}（{date_str}，{doc.overtime_hours or '?'}H）",
                    attend_desc="考勤表对应日期无加班记录",
                    detail=f"有加班单据但考勤表未登记加班（置信度:{doc.confidence}）",
                ))
            else:
                docs_matched += 1

    # 2. 考勤表缺单据核对（仅对有高置信度单据覆盖的人员，避免手写单据导致大量误报）
    attendance_leave_without_doc = 0
    attendance_overtime_without_doc = 0
    covered_employees = set(leave_docs.keys()) | set(overtime_docs.keys())

    for name in sorted(table.days):
        if name not in covered_employees:
            continue  # 该人员无任何高置信度单据，不做缺单核对
        for d, rec in table.days[name].items():
            if rec.mark_up in LEAVE_MARKS or rec.mark_down in LEAVE_MARKS:
                if name not in leave_docs or d not in leave_docs[name]:
                    attendance_leave_without_doc += 1
                    diffs.append(Diff(
                        category="单据核对", name=name, on_date=d, level=LV_SUSPECT,
                        raw_desc="PDF无对应请假单据",
                        attend_desc=f"上={rec.mark_up or '-'} 下={rec.mark_down or '-'}",
                        detail="考勤表有假单标记但PDF中未找到对应请假单据（该人员有其他单据，此条可能缺单或OCR未识别）",
                    ))
            if rec.overtime_h > 0:
                if name not in overtime_docs or d not in overtime_docs[name]:
                    attendance_overtime_without_doc += 1
                    diffs.append(Diff(
                        category="单据核对", name=name, on_date=d, level=LV_SUSPECT,
                        raw_desc="PDF无对应加班单据",
                        attend_desc=f"加={rec.overtime_h:g}H",
                        detail=f"考勤表记了加班{rec.overtime_h:g}H但PDF中未找到对应加班单据",
                    ))

    return DocReconcileResult(
        diffs=diffs,
        docs_total=len([d for d in docs if d.doc_type not in ("attendance_sheet", "overtime_agreement", "unknown")]),
        docs_matched=docs_matched,
        docs_unmatched=docs_unmatched,
        docs_manual_review=docs_manual_review,
        attendance_leave_without_doc=attendance_leave_without_doc,
        attendance_overtime_without_doc=attendance_overtime_without_doc,
    )
