#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从「1688采购助手-全店导出」xlsx 提取【未标黄】的【宝贝链接】列, 存为 data/links.json。
标黄判定: 宝贝链接(第3列)单元格填充为黄色 FFFFFF00 即视为已处理(跳过)。

用法: python3 extract_links.py [xlsx路径]
"""
import sys, os, json, openpyxl

DEFAULT_XLSX = "~/Desktop/1688采购助手-全店导出.xlsx"
LINK_COL = 3          # 宝贝链接列
YELLOW = "FFFFFF00"   # 标黄填充色


def extract(xlsx_path):
    wb = openpyxl.load_workbook(xlsx_path)
    ws = wb.active
    links = []
    for r in range(2, ws.max_row + 1):
        c = ws.cell(row=r, column=LINK_COL)
        f = c.fill
        is_yellow = bool(f and f.patternType == "solid" and f.fgColor and f.fgColor.rgb == YELLOW)
        if not is_yellow and c.value:
            links.append(str(c.value).strip())
    return links


if __name__ == "__main__":
    xlsx = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_XLSX
    links = extract(xlsx)
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "links.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    json.dump(links, open(out, "w"), ensure_ascii=False, indent=0)
    print(f"未标黄链接 {len(links)} 条 -> {out}")
    print(f"按每批 50 个, 共 {(len(links)+49)//50} 批")
