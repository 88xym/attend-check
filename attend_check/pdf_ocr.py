# -*- coding: utf-8 -*-
"""PDF OCR 提取模块。

将扫描版 PDF 逐页渲染为图片，用 rapidocr 识别文字，结果缓存为 JSON。
缓存命中时跳过 OCR，支持增量处理。
"""
import json
import os
from dataclasses import dataclass, field, asdict
from typing import Optional

import pymupdf


@dataclass
class OcrLine:
    """单行 OCR 结果。"""
    text: str
    conf: float
    box: list  # [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]

    @property
    def y(self) -> float:
        """行中心 y 坐标（用于排序）。"""
        return sum(p[1] for p in self.box) / 4

    @property
    def x(self) -> float:
        return sum(p[0] for p in self.box) / 4


@dataclass
class OcrPage:
    """单页 OCR 结果。"""
    page_num: int
    width: float
    height: float
    lines: list[OcrLine] = field(default_factory=list)

    @property
    def full_text(self) -> str:
        """按阅读顺序拼接的全文。"""
        sorted_lines = sorted(self.lines, key=lambda l: (round(l.y / 20), l.x))
        return "\n".join(l.text for l in sorted_lines)

    def to_dict(self) -> dict:
        return {
            "page_num": self.page_num,
            "width": self.width,
            "height": self.height,
            "lines": [asdict(l) for l in self.lines],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "OcrPage":
        return cls(
            page_num=d["page_num"],
            width=d["width"],
            height=d["height"],
            lines=[OcrLine(**l) for l in d["lines"]],
        )


class PdfOcr:
    """PDF OCR 提取器，带磁盘缓存。"""

    def __init__(self, pdf_path: str, cache_path: Optional[str] = None, dpi: int = 200):
        self.pdf_path = pdf_path
        self.dpi = dpi
        if cache_path is None:
            cache_path = os.path.splitext(pdf_path)[0] + "_ocr_cache.json"
        self.cache_path = cache_path
        self._cache: dict[int, OcrPage] = {}
        self._load_cache()

    def _load_cache(self):
        if os.path.exists(self.cache_path):
            with open(self.cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for k, v in data.items():
                self._cache[int(k)] = OcrPage.from_dict(v)

    def _save_cache(self):
        data = {str(k): v.to_dict() for k, v in self._cache.items()}
        with open(self.cache_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)

    def ocr_page(self, page_num: int, force: bool = False) -> OcrPage:
        """OCR 单页（1-based）。命中缓存且非 force 时跳过。"""
        if page_num in self._cache and not force:
            return self._cache[page_num]

        from rapidocr_onnxruntime import RapidOCR
        ocr = RapidOCR()

        doc = pymupdf.open(self.pdf_path)
        page = doc[page_num - 1]
        page_w = page.rect.width
        page_h = page.rect.height
        pix = page.get_pixmap(dpi=self.dpi)
        img_bytes = pix.tobytes("png")
        doc.close()

        import numpy as np
        from PIL import Image
        import io
        img = np.array(Image.open(io.BytesIO(img_bytes)))

        result, _ = ocr(img)
        lines = []
        if result:
            for item in result:
                box, text, conf = item[0], item[1], float(item[2])
                lines.append(OcrLine(text=text, conf=conf, box=box))

        page_result = OcrPage(
            page_num=page_num,
            width=page_w,
            height=page_h,
            lines=lines,
        )
        self._cache[page_num] = page_result
        self._save_cache()
        return page_result

    def ocr_all(self, force: bool = False, progress_cb=None) -> list[OcrPage]:
        """OCR 全部页。"""
        doc = pymupdf.open(self.pdf_path)
        total = len(doc)
        doc.close()

        results = []
        for i in range(1, total + 1):
            page = self.ocr_page(i, force=force)
            results.append(page)
            if progress_cb:
                progress_cb(i, total)
        return results

    def get_page(self, page_num: int) -> Optional[OcrPage]:
        """获取已缓存的页结果（不触发 OCR）。"""
        return self._cache.get(page_num)

    @property
    def total_pages(self) -> int:
        doc = pymupdf.open(self.pdf_path)
        n = len(doc)
        doc.close()
        return n
