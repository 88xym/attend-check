# -*- coding: utf-8 -*-
"""考勤对账入口（阶段二：原始打卡 × 手工考勤表 × PDF单据 三方核对）。

用法：
    python main.py                 # 使用 config.json 默认配置
    python main.py --config xxx.json
    python main.py --report out.xlsx
    python main.py --skip-ocr      # 跳过 OCR（使用已有缓存）
    python main.py --reocr         # 强制重新 OCR
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime

from attend_check.loader import load_attendance, load_raw
from attend_check.name_map import NameMapper
from attend_check.report import build_report
from attend_check.rules import (CheckResult, build_punch_index, check_name_matching,
                                check_presence, check_totals)


def load_config(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def main() -> int:
    ap = argparse.ArgumentParser(description="考勤对账（阶段二：三方核对）")
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--report", default=None, help="差异报告输出路径")
    ap.add_argument("--skip-ocr", action="store_true", help="跳过 PDF OCR（使用缓存）")
    ap.add_argument("--reocr", action="store_true", help="强制重新 OCR 全部页")
    ap.add_argument("--no-docs", action="store_true", help="不做单据核对（仅阶段一）")
    args = ap.parse_args()

    cfg = load_config(args.config)
    base = os.path.dirname(os.path.abspath(args.config))
    raw_path = os.path.join(base, cfg["raw_file"])
    attend_path = os.path.join(base, cfg["attend_file"])
    pdf_path = os.path.join(base, cfg.get("pdf_file", ""))
    period_start = parse_date(cfg["period"]["start"])
    period_end = parse_date(cfg["period"]["end"])
    out_path = args.report or os.path.join(base, cfg.get("output_dir", "output"),
                                           f"考勤对账差异报告_{cfg['period']['start']}_{cfg['period']['end']}.xlsx")

    print(f"[1/5] 读取原始打卡记录: {raw_path}")
    punches = load_raw(raw_path)
    print(f"      共 {len(punches)} 条打卡记录")

    print(f"[2/5] 解析手工考勤表: {attend_path} [{cfg['main_sheet']}]")
    mapper = NameMapper(os.path.join(base, cfg.get("name_alias_file", "aliases.json")))
    table = load_attendance(attend_path, cfg["main_sheet"], period_start, period_end,
                            name_normalize=mapper.normalize)
    print(f"      员工 {len(table.days)} 人，日期 {len(table.dates())} 天")
    if table.extra_rows:
        print(f"      表尾非员工行（已跳过）: {table.extra_rows}")

    print("[3/5] 执行对账规则（含姓名配对核对）")
    punch_idx = build_punch_index(punches, mapper)
    name_pairs = check_name_matching(punches, mapper, set(table.days))
    n_ok = sum(1 for p in name_pairs if p.status == "已配对")
    n_only_att = sum(1 for p in name_pairs if p.status == "仅考勤表")
    n_only_raw = sum(1 for p in name_pairs if p.status == "仅原始记录")
    print(f"      姓名配对: 已配对 {n_ok}，仅考勤表 {n_only_att}，仅原始记录 {n_only_raw}")
    if n_only_att:
        print(f"        仅考勤表: {[p.name for p in name_pairs if p.status == '仅考勤表']}")
    if n_only_raw:
        print(f"        仅原始记录: {[p.name for p in name_pairs if p.status == '仅原始记录']}")

    result = CheckResult()
    for d in check_presence(punch_idx, table, mapper):
        result.add(d)
    for d in check_totals(table):
        result.add(d)

    # ---- 阶段二：PDF 单据 OCR + 三方核对 ----
    doc_records = []
    doc_reconcile = None
    if not args.no_docs and pdf_path and os.path.exists(pdf_path):
        print(f"[4/5] PDF 单据 OCR 与解析: {pdf_path}")
        from attend_check.pdf_ocr import PdfOcr
        from attend_check.doc_parser import parse_all
        from attend_check.reconcile_docs import reconcile_docs

        cache_path = os.path.join(base, cfg.get("output_dir", "output"), "pdf_ocr_cache.json")
        ocr = PdfOcr(pdf_path, cache_path=cache_path)
        total = ocr.total_pages
        print(f"      共 {total} 页，{'使用缓存' if (not args.reocr and ocr._cache) else '重新 OCR'}")

        def _progress(i, tot):
            if i % 10 == 0 or i == tot:
                print(f"      OCR 进度: {i}/{tot}")

        pages = ocr.ocr_all(force=args.reocr, progress_cb=_progress)
        name_pool = list(table.days) + [p.name for p in name_pairs]
        doc_records = parse_all(pages, name_pool=name_pool)

        type_count = {}
        for r in doc_records:
            type_count[r.doc_type_label] = type_count.get(r.doc_type_label, 0) + 1
        print(f"      解析单据: {len(doc_records)} 页 -> {type_count}")

        doc_reconcile = reconcile_docs(doc_records, table, mapper)
        for d in doc_reconcile.diffs:
            result.add(d)
        print(f"      单据核对: 匹配 {doc_reconcile.docs_matched}，未匹配 {doc_reconcile.docs_unmatched}，"
              f"考勤表缺单据 {doc_reconcile.attendance_leave_without_doc + doc_reconcile.attendance_overtime_without_doc}")
    else:
        print("[4/5] 跳过 PDF 单据核对（--no-docs 或无 PDF 文件）")

    print("[5/5] 生成差异报告")
    path = build_report(result, (period_start, period_end), out_path,
                        name_pairs=name_pairs, doc_records=doc_records)
    by_level = result.by_level()
    print(f"\n=== 完成 ===")
    print(f"差异总数: {len(result.diffs)}")
    print(f"  硬错误: {by_level.get('硬错误', 0)}")
    print(f"  可疑项: {by_level.get('可疑项', 0)}")
    print(f"报告已生成: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
