# -*- coding: utf-8 -*-
"""考勤对账入口（阶段三：配置化一键运行）。

用法：
    python main.py                    # 使用 config.json，一键完成全部对账
    python main.py --config xxx.json  # 指定配置文件
    python main.py --skip-ocr         # 跳过 OCR（使用缓存）
    python main.py --reocr            # 强制重新 OCR
    python main.py --no-docs          # 仅阶段一（不做单据核对）
    python main.py --report out.xlsx  # 指定报告输出路径

换月操作：修改 config.json 中的 period 和 files 路径，运行 python main.py 即可。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime


def load_config(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def _cfg_get(cfg: dict, *keys, default=None):
    """支持新旧配置格式的兼容读取。"""
    # 新格式：嵌套 dict
    d = cfg
    for k in keys:
        if isinstance(d, dict) and k in d:
            d = d[k]
        else:
            # 回退到旧格式（扁平 key）
            flat = "_".join(keys)
            if flat in cfg:
                return cfg[flat]
            return default
    return d


def main() -> int:
    ap = argparse.ArgumentParser(description="考勤对账（原始打卡 × 手工考勤表 × PDF单据）")
    ap.add_argument("--config", default="config.json", help="配置文件路径")
    ap.add_argument("--report", default=None, help="差异报告输出路径（覆盖配置）")
    ap.add_argument("--skip-ocr", action="store_true", help="跳过 PDF OCR（使用缓存）")
    ap.add_argument("--reocr", action="store_true", help="强制重新 OCR 全部页")
    ap.add_argument("--no-docs", action="store_true", help="不做单据核对（仅阶段一）")
    args = ap.parse_args()

    cfg = load_config(args.config)
    base = os.path.dirname(os.path.abspath(args.config))

    # ---- 读取配置 ----
    period_start = parse_date(_cfg_get(cfg, "period", "start"))
    period_end = parse_date(_cfg_get(cfg, "period", "end"))

    raw_file = _cfg_get(cfg, "files", "raw", default=cfg.get("raw_file", ""))
    attend_file = _cfg_get(cfg, "files", "attendance", default=cfg.get("attend_file", ""))
    attend_sheet = _cfg_get(cfg, "files", "attendance_sheet", default=cfg.get("main_sheet", ""))
    pdf_file = _cfg_get(cfg, "files", "pdf", default=cfg.get("pdf_file", ""))
    alias_file = _cfg_get(cfg, "files", "aliases", default=cfg.get("name_alias_file", "aliases.json"))

    out_dir = _cfg_get(cfg, "output", "dir", default=cfg.get("output_dir", "output"))
    report_template = _cfg_get(cfg, "output", "report_template",
                               default="考勤对账差异报告_{start}_{end}.xlsx")

    ocr_enabled = _cfg_get(cfg, "ocr", "enabled", default=True)
    ocr_dpi = _cfg_get(cfg, "ocr", "dpi", default=200)
    ocr_cache_file = _cfg_get(cfg, "ocr", "cache_file", default="pdf_ocr_cache.json")

    rules = cfg.get("rules", {})
    check_presence = rules.get("check_presence", True)
    check_totals = rules.get("check_totals", True)
    check_docs = rules.get("check_docs", True) and not args.no_docs

    # ---- 路径解析 ----
    raw_path = os.path.join(base, raw_file)
    attend_path = os.path.join(base, attend_file)
    pdf_path = os.path.join(base, pdf_file) if pdf_file else ""
    alias_path = os.path.join(base, alias_file)
    out_dir_path = os.path.join(base, out_dir)
    os.makedirs(out_dir_path, exist_ok=True)

    report_name = report_template.format(start=period_start, end=period_end)
    out_path = args.report or os.path.join(out_dir_path, report_name)

    # ---- 文件存在性检查 ----
    for label, p in [("原始打卡记录", raw_path), ("考勤表", attend_path)]:
        if not os.path.exists(p):
            print(f"[错误] 找不到{label}: {p}")
            print(f"       请检查 config.json 中的 files.{label} 配置")
            return 1

    # ================================================================
    # [1/5] 读取原始打卡记录
    # ================================================================
    from attend_check.loader import load_attendance, load_raw
    print(f"[1/5] 读取原始打卡记录: {raw_path}")
    punches = load_raw(raw_path)
    print(f"      共 {len(punches)} 条打卡记录")

    # ================================================================
    # [2/5] 解析手工考勤表
    # ================================================================
    from attend_check.name_map import NameMapper
    print(f"[2/5] 解析手工考勤表: {attend_path} [{attend_sheet}]")
    mapper = NameMapper(alias_path)
    table = load_attendance(attend_path, attend_sheet, period_start, period_end,
                            name_normalize=mapper.normalize)
    print(f"      员工 {len(table.days)} 人，日期 {len(table.dates())} 天")
    if table.extra_rows:
        print(f"      表尾非员工行（已跳过）: {table.extra_rows}")

    # ================================================================
    # [3/5] 执行对账规则
    # ================================================================
    from attend_check.rules import (CheckResult, build_punch_index,
                                    check_name_matching, check_presence, check_totals)
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
    if check_presence:
        for d in check_presence(punch_idx, table, mapper):
            result.add(d)
        print(f"      到场核对: 已执行")
    else:
        print(f"      到场核对: 已跳过（配置关闭）")

    if check_totals:
        for d in check_totals(table):
            result.add(d)
        print(f"      累计重算: 已执行")
    else:
        print(f"      累计重算: 已跳过（配置关闭）")

    # ================================================================
    # [4/5] PDF 单据 OCR + 三方核对
    # ================================================================
    doc_records = []
    doc_reconcile = None
    if check_docs and ocr_enabled and pdf_path and os.path.exists(pdf_path):
        print(f"[4/5] PDF 单据 OCR 与解析: {pdf_path}")
        from attend_check.pdf_ocr import PdfOcr
        from attend_check.doc_parser import parse_all
        from attend_check.reconcile_docs import reconcile_docs

        cache_path = os.path.join(out_dir_path, ocr_cache_file)
        ocr = PdfOcr(pdf_path, cache_path=cache_path, dpi=ocr_dpi)
        total = ocr.total_pages
        using_cache = (not args.reocr) and bool(ocr._cache)
        print(f"      共 {total} 页，{'使用缓存' if using_cache else '重新 OCR'}（DPI={ocr_dpi}）")

        def _progress(i, tot):
            if i % 10 == 0 or i == tot:
                print(f"      OCR 进度: {i}/{tot}")

        if args.skip_ocr and using_cache:
            pages = [ocr.get_page(i) for i in range(1, total + 1)]
            pages = [p for p in pages if p is not None]
        else:
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
        if doc_reconcile.docs_manual_review:
            print(f"      需人工复核（低置信度手写单据）: {doc_reconcile.docs_manual_review} 张")
    else:
        reason = []
        if not check_docs:
            reason.append("配置关闭")
        if not ocr_enabled:
            reason.append("OCR 关闭")
        if args.no_docs:
            reason.append("--no-docs")
        if not pdf_path or not os.path.exists(pdf_path):
            reason.append("无 PDF 文件")
        print(f"[4/5] 跳过 PDF 单据核对（{'、'.join(reason)}）")

    # ================================================================
    # [5/5] 生成差异报告
    # ================================================================
    from attend_check.report import build_report
    print("[5/5] 生成差异报告")
    path = build_report(result, (period_start, period_end), out_path,
                        name_pairs=name_pairs, doc_records=doc_records)
    by_level = result.by_level()
    print(f"\n=== 完成 ===")
    print(f"考勤周期: {period_start} ~ {period_end}")
    print(f"差异总数: {len(result.diffs)}")
    print(f"  硬错误: {by_level.get('硬错误', 0)}")
    print(f"  可疑项: {by_level.get('可疑项', 0)}")
    print(f"报告已生成: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
