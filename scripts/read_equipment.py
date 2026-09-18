# -*- coding: utf-8 -*-
"""设备一览表读取 —— 灵活识别介质列，输出 基础位号→介质 映射。

用法:
  python read_equipment.py <设备一览表.xlsx> [--out base_media.json]

设计要点（不写死列位置）:
  - 逐 sheet 扫描前若干行找表头行
  - 空白规范化后按关键字匹配：位号列、介质列
  - 换热器类的"介质"表头下常有 壳程/管程 双子列，全部纳入
  - 键用"基础位号"(去尾缀)，因为设备表与布置图尾缀经常不一致
"""
import sys
import re
import json
import argparse
import warnings

warnings.filterwarnings('ignore')
sys.stdout.reconfigure(encoding='utf-8')

import os  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import get_base_tag, is_equipment_tag  # noqa: E402

import openpyxl  # noqa: E402

MEDIA_KW = ['介质', '物料', '主要成分', '主要介质']
TAG_KW = ['位号', '设备位号']
# 换热器双介质子列关键字（同一"介质"大表头下的分列：壳程/管程）
SUBCOL_KW = ['壳程', '管程', '壳侧', '管侧']
# 会误含子列关键字、但本身不是介质的相邻大表头（操作温度/压力/材质等也分壳程管程）
OTHER_PARENT_KW = ['温度', '压力', '材质', '数量', '规格', '型号', '备注', '图号', '来源']
# 排除的非工艺介质（公用工程/传热介质）——不影响读取，仅供上层分类时参考
SKIP_SHEET_KW = ['封头容积', '管径计算', '罐容积']


def norm(s):
    """规范化：去所有空白字符，便于表头关键字匹配。"""
    return re.sub(r'\s+', '', str(s)) if s is not None else ''


def find_header(rows, scan_rows=8):
    """在前 scan_rows 行里定位表头，返回 (header_row_idx, tag_col, media_cols)。

    换热器类"介质"大表头下会分壳程/管程两个子列，但相邻的
    操作温度/压力/材质等大表头同样分壳程/管程。因此：
      1. 先找到所有大表头列（含各自的关键字类型）
      2. 只把"介质"大表头，及其到下一个非介质大表头之间的
         壳程/管程子列，纳入 media_cols
    """
    tag_col = None
    header_row = None
    # 收集大表头（介质列 / 其他列）与子列
    media_parents = []   # (col) 介质大表头列
    other_parents = []   # (col) 温度/压力/材质等大表头列
    subcols = []         # (col) 壳程/管程子列
    for r in range(min(scan_rows, len(rows))):
        for c, val in enumerate(rows[r]):
            s = norm(val)
            if not s:
                continue
            if any(k in s for k in MEDIA_KW):
                if c not in media_parents:
                    media_parents.append(c)
                    header_row = r if header_row is None else header_row
            elif any(k in s for k in OTHER_PARENT_KW):
                if c not in other_parents:
                    other_parents.append(c)
            elif any(k in s for k in SUBCOL_KW):
                if c not in subcols:
                    subcols.append(c)
            if tag_col is None and any(k in s for k in TAG_KW):
                tag_col = c

    boundaries = sorted(other_parents + media_parents)
    media_cols = set(media_parents)
    # 每个介质大表头，纳入它到"下一个大表头"之间的壳程/管程子列
    for mp in media_parents:
        nxt = min([b for b in boundaries if b > mp], default=float('inf'))
        for sc in subcols:
            if mp < sc < nxt:
                media_cols.add(sc)
    return header_row, tag_col, sorted(media_cols)


def read_sheet(sheet):
    """读取单个 sheet，返回 {基础位号: 介质文本}。"""
    rows = list(sheet.iter_rows(values_only=True))
    if not rows:
        return {}
    header_row, tag_col, media_cols = find_header(rows)
    if tag_col is None or not media_cols:
        return {}
    # 数据从表头行之后开始；用 is_equipment_tag 兜底跳过非数据行
    result = {}
    start = (header_row + 1) if header_row is not None else 5
    for row in rows[start:]:
        if not row or len(row) <= tag_col or row[tag_col] is None:
            continue
        tag = str(row[tag_col]).strip()
        if not is_equipment_tag(tag, loose=True):
            continue
        parts = [str(row[c]).strip() for c in media_cols
                 if len(row) > c and row[c] not in (None, '')]
        if parts:
            result[get_base_tag(tag)] = '、'.join(parts)
    return result


def read_equipment(xlsx_path):
    wb = openpyxl.load_workbook(xlsx_path, data_only=True)
    base_media = {}
    per_sheet = {}
    for name in wb.sheetnames:
        if any(k in name for k in SKIP_SHEET_KW):
            continue
        got = read_sheet(wb[name])
        if got:
            per_sheet[name] = len(got)
            # 后出现的 sheet 不覆盖已有键（同一系列以先读到的为准）
            for k, v in got.items():
                base_media.setdefault(k, v)
    return base_media, per_sheet


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('xlsx')
    ap.add_argument('--out', default='base_media.json')
    args = ap.parse_args()

    base_media, per_sheet = read_equipment(args.xlsx)
    with open(args.out, 'w', encoding='utf-8') as f:
        json.dump(base_media, f, ensure_ascii=False, indent=2)

    print(f'设备表: {args.xlsx}')
    for name, n in per_sheet.items():
        print(f'  [{name[:20]}] {n} 台')
    print(f'基础位号合计: {len(base_media)} 个')
    print(f'已写入: {args.out}')


if __name__ == '__main__':
    main()
