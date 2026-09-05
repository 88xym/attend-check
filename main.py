# -*- coding: utf-8 -*-
"""考勤对账入口（阶段一：原始打卡记录 × 手工考勤表）。

用法：
    python main.py                 # 使用 config.json 默认配置
    python main.py --config xxx.json
    python main.py --report out.xlsx
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
    ap = argparse.ArgumentParser(description="考勤对账（阶段一）")
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--report", default=None, help="差异报告输出路径（默认 output/考勤对账差异报告.xlsx）")
    args = ap.parse_args()

    cfg = load_config(args.config)
    base = os.path.dirname(os.path.abspath(args.config))
    raw_path = os.path.join(base, cfg["raw_file"])
    attend_path = os.path.join(base, cfg["attend_file"])
    period_start = parse_date(cfg["period"]["start"])
    period_end = parse_date(cfg["period"]["end"])
    out_path = args.report or os.path.join(base, cfg.get("output_dir", "output"),
                                           f"考勤对账差异报告_{cfg['period']['start']}_{cfg['period']['end']}.xlsx")

    print(f"[1/4] 读取原始打卡记录: {raw_path}")
    punches = load_raw(raw_path)
    print(f"      共 {len(punches)} 条打卡记录")

    print(f"[2/4] 解析手工考勤表: {attend_path} [{cfg['main_sheet']}]")
    mapper = NameMapper(os.path.join(base, cfg.get("name_alias_file", "aliases.json")))
    table = load_attendance(attend_path, cfg["main_sheet"], period_start, period_end,
                            name_normalize=mapper.normalize)
    print(f"      员工 {len(table.days)} 人，日期 {len(table.dates())} 天")
    if table.extra_rows:
        print(f"      表尾非员工行（已跳过）: {table.extra_rows}")

    print("[3/4] 执行对账规则（含姓名配对核对）")
    punch_idx = build_punch_index(punches, mapper)
    name_pairs = check_name_matching(punches, mapper, set(table.days))
    n_ok = sum(1 for p in name_pairs if p.status == "已配对")
    n_only_att = sum(1 for p in name_pairs if p.status == "仅考勤表")
    n_only_raw = sum(1 for p in name_pairs if p.status == "仅原始记录")
    print(f"      姓名配对: 已配对 {n_ok}，仅考勤表 {n_only_att}，仅原始记录 {n_only_raw}")
    if n_only_att:
        print(f"        仅考勤表（考勤表有人但无打卡记录）: "
              f"{[p.name for p in name_pairs if p.status == '仅考勤表']}")
    if n_only_raw:
        print(f"        仅原始记录（有打卡但不在考勤表主表）: "
              f"{[p.name for p in name_pairs if p.status == '仅原始记录']}")

    result = CheckResult()
    for d in check_presence(punch_idx, table, mapper):
        result.add(d)
    for d in check_totals(table):
        result.add(d)

    print("[4/4] 生成差异报告")
    path = build_report(result, (period_start, period_end), out_path, name_pairs=name_pairs)
    by_level = result.by_level()
    print(f"\n=== 完成 ===")
    print(f"差异总数: {len(result.diffs)}")
    print(f"  硬错误: {by_level.get('硬错误', 0)}")
    print(f"  可疑项: {by_level.get('可疑项', 0)}")
    print(f"报告已生成: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
