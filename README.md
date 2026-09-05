# 考勤对账工具（机场项目）

自动对账程序：**原始打卡记录 × 手工考勤表 × PDF 支撑单据**，三方核对后输出分级差异报告。

- **阶段一（已完成）**：原始打卡记录 ↔ 手工考勤表，规则对账 + 月度累计重算
- **阶段二（已完成）**：PDF 扫描单据 OCR → 请假/加班单三方核对
- **阶段三（进行中）**：配置化一键运行，每考勤周期可复用

## 项目结构

```
D:\ATTEND\
├── main.py                  # 入口（配置化一键运行）
├── config.json              # 配置（周期、文件、规则开关、OCR参数）
├── aliases.json             # 姓名别名映射（繁简/别名归一到简体）
├── requirements.txt         # Python 依赖
├── attend_check/            # 核心包
│   ├── loader.py            # 解析原始打卡记录 + 手工考勤表
│   ├── name_map.py          # 姓名标准化（opencc繁简 + 别名 + 模糊建议）
│   ├── rules.py             # 对账规则引擎（到场核对 + 累计重算）
│   ├── pdf_ocr.py           # PDF OCR 提取（rapidocr，带磁盘缓存）
│   ├── doc_parser.py        # 单据类型识别 + 字段提取
│   ├── reconcile_docs.py    # 单据 × 考勤表三方核对
│   └── report.py            # Excel 差异报告生成
├── tests/                   # 单元测试
└── output/                  # 差异报告 + OCR缓存（不入库）
```

## 环境要求

- Python 3.10+
- 依赖：`pip install -r requirements.txt`
  - openpyxl（Excel读写）
  - opencc-python-reimplemented（繁简转换）
  - pymupdf（PDF渲染）
  - rapidocr-onnxruntime（本地OCR，不联网）
  - Pillow、numpy

## 快速开始

```bash
pip install -r requirements.txt
python main.py
```

**换月操作**：把新的三个源文件（原始记录.xlsx、考勤表.xlsx、单据.pdf）放到项目目录，运行 `python main.py` 即可。程序自动识别文件名和考勤周期，无需改配置。

输出：`output/考勤对账差异报告_<周期开始>_<周期结束>.xlsx`

## 自动检测

`config.json` 中 `files` 和 `period` 留空时，程序自动扫描目录：

- 含"原始记录"/"打卡"的 xlsx → 原始打卡记录
- 含"考勤"的 xlsx → 手工考勤表（自动识别 sheet 名）
- 目录下最新的 pdf → 单据 PDF
- 从文件名提取周期（如 `原始记录表(20260721-20260820).xlsx` → 2026-07-21~2026-08-20）

如需指定具体文件，在 `config.json` 中填入文件名即可覆盖自动检测。

## 配置说明（config.json）

换月只需修改配置，无需改代码：

```json
{
  "period": { "start": "2026-07-21", "end": "2026-08-20" },
  "files": {
    "raw": "原始记录表.xlsx",
    "attendance": "考勤表.xlsx",
    "attendance_sheet": "考勤表721-820",
    "pdf": "单据.pdf",
    "aliases": "aliases.json"
  },
  "output": {
    "dir": "output",
    "report_template": "考勤对账差异报告_{start}_{end}.xlsx"
  },
  "ocr": { "enabled": true, "dpi": 200, "cache_file": "pdf_ocr_cache.json" },
  "rules": {
    "check_presence": true,
    "check_totals": true,
    "check_docs": true,
    "single_punch_reminder": true,
    "weekend_attendance_check": true
  }
}
```

### 命令行参数

| 参数 | 说明 |
|---|---|
| `--config xxx.json` | 指定配置文件 |
| `--report out.xlsx` | 指定报告输出路径 |
| `--skip-ocr` | 跳过 OCR（使用缓存） |
| `--reocr` | 强制重新 OCR 全部页 |
| `--no-docs` | 仅阶段一（不做单据核对） |

## 报告内容（7个Sheet）

1. **差异汇总**：各差异类别数量统计
2. **到场核对明细**：有打卡无记录 / 无打卡有√ / 缺卡提醒 / 加班无佐证
3. **累计重算明细**：月度累计列 vs 逐日标记求和
4. **姓名配对**：原始记录与考勤表姓名归一化配对结果 + 模糊建议
5. **单据核对明细**：有单据无考勤 / 考勤缺单据 / 加班时数不一致
6. **单据清单**：PDF 全部单据列表（含类型、置信度、需人工复核标注）
7. **全部差异**：完整明细（可按类别/级别筛选）

差异分级：
- 🔴 **硬错误**：数据自相矛盾，必须修正
- 🟡 **可疑项**：需人工查证

## 考勤规则（程序判定口径）

- **工作日**：周一至周五全天上班，出勤记 √
- **周六**：上午半天班，出勤记 √（仅1次打卡属正常，不报缺卡）
- **周日**：休息日；出勤需有"休息日上班"数字佐证
- **标记体系**：√/曠/加/培/差/補/年/事/病/其（含產/喪/婚，计入"其（d）"列）
- **姓名**：opencc 简繁统一，别名可配置，未配对自动给模糊建议

## OCR 说明

- 引擎：rapidocr-onnxruntime（纯本地，不联网，不上传数据）
- 打印体（加班申请单）：自动核对，准确率高
- 手写体（休假申请单、司机加班单）：列清单 + 标记"需人工复核"，不做自动差异核对
- 缓存：OCR 结果存 `output/pdf_ocr_cache.json`，重复运行秒级完成

## 数据文件说明

原始考勤数据（xlsx/pdf）含员工个人信息，**默认不纳入 Git 版本管理**（见 `.gitignore`）。

## GitHub 仓库

https://github.com/88xym/attend-check（私有）
