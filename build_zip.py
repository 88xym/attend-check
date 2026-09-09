# -*- coding: utf-8 -*-
"""打包项目为 zip，排除源数据、输出、缓存和 git。"""
import os
import zipfile

ROOT = r"D:\ATTEND"
OUT = os.path.join(ROOT, "attend-check.zip")

# 排除规则
EXCLUDE_DIRS = {".git", "__pycache__", "inputfile", "output", ".pytest_cache"}
EXCLUDE_EXTS = {".xlsx", ".xls", ".pdf", ".csv", ".pyc", ".zip", ".png", ".jpg", ".jpeg"}
EXCLUDE_PREFIXES = ("~$",)


def should_skip(rel_path: str) -> bool:
    parts = rel_path.replace("\\", "/").split("/")
    # 排除目录
    if any(p in EXCLUDE_DIRS for p in parts):
        return True
    # 排除扩展名
    if os.path.splitext(rel_path)[1].lower() in EXCLUDE_EXTS:
        return True
    # 排除临时文件
    if os.path.basename(rel_path).startswith(EXCLUDE_PREFIXES):
        return True
    return False


count = 0
with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as zf:
    for root, dirs, files in os.walk(ROOT):
        # 原地修改 dirs 以跳过排除目录
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        for f in files:
            full = os.path.join(root, f)
            rel = os.path.relpath(full, ROOT)
            if should_skip(rel):
                continue
            # zip 内路径用正斜杠
            arcname = rel.replace("\\", "/")
            zf.write(full, arcname)
            count += 1
            print(f"  + {arcname}")

size = os.path.getsize(OUT) / 1024
print(f"\n打包完成: {OUT}")
print(f"共 {count} 个文件，{size:.1f} KB")
