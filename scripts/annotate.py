# -*- coding: utf-8 -*-
"""介质报警标注生成 —— 分类 + 二级分组标注。

用法:
  python annotate.py --frames _frames.json --media base_media.json \
                     --props 物性表.xlsx --out 标注.dxf \
                     [--oxygen-tags C1001,DR2001] [--title-prefix 图框]

分类规则:
  - 可燃: 介质中任一物料的"火灾危险性类别"为甲类或乙类 (GB 50016-2014)
  - 有毒: 介质中任一物料"被列入有毒气体检测目录"为"是"
  - 氧含量报警: 介质含"氮/N2"，或该设备位号在 --oxygen-tags 中显式指定

标注布局:
  - 每个图框独立，标注全部落在图框四角内
  - 左上角二级分组竖排: 【类别】→ ● 物料(n台) → 设备位号+引线到设备
"""
import sys
import os
import re
import json
import argparse
import warnings
from collections import defaultdict

warnings.filterwarnings('ignore')
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import (get_base_tag, split_media, is_combustible_fire_class,  # noqa: E402
                 CLASS_COMBUSTIBLE, CLASS_TOXIC, CLASS_OXYGEN,
                 CLASS_ORDER, LAYER_CFG)

import ezdxf  # noqa: E402
import openpyxl  # noqa: E402

# ── 物性表列识别关键字 ──
NAME_KW = ['化学品名称', '名称', '物料名称', '介质名称']
FIRE_KW = ['火灾危险性', '火灾类别']
TOXIC_KW = ['有毒气体检测目录', '有毒气体', '毒性检测']
# 氮气识别
NITROGEN_RE = re.compile(r'氮|N2|N₂', re.IGNORECASE)


def norm(s):
    return re.sub(r'\s+', '', str(s)) if s is not None else ''


def load_props(xlsx_path):
    """读物性表 -> {物料名: {'combustible': bool, 'toxic': bool}}。

    灵活识别列：化学品名称 / 火灾危险性类别 / 是否被列入有毒气体检测目录。
    """
    wb = openpyxl.load_workbook(xlsx_path, data_only=True)
    props = {}
    for ws in wb.worksheets:
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            continue
        name_col = fire_col = toxic_col = header_row = None
        for r in range(min(5, len(rows))):
            for c, val in enumerate(rows[r]):
                s = norm(val)
                if not s:
                    continue
                if name_col is None and any(k in s for k in NAME_KW):
                    name_col, header_row = c, r
                if fire_col is None and any(k in s for k in FIRE_KW):
                    fire_col = c
                if toxic_col is None and any(k in s for k in TOXIC_KW):
                    toxic_col = c
            if name_col is not None and fire_col is not None:
                break
        if name_col is None or header_row is None:
            continue
        for row in rows[header_row + 1:]:
            if len(row) <= name_col or not row[name_col]:
                continue
            name = str(row[name_col]).strip()
            if not name:
                continue
            fire = str(row[fire_col]).strip() if fire_col is not None and len(row) > fire_col and row[fire_col] else ''
            toxic_v = str(row[toxic_col]).strip() if toxic_col is not None and len(row) > toxic_col and row[toxic_col] else ''
            props[name] = {
                'combustible': is_combustible_fire_class(fire),
                'toxic': ('是' in toxic_v or '应设' in toxic_v),
            }
        if props:
            break  # 主表通常在第一个 sheet
    return props


def classify(media_str, props, tag, oxygen_tags):
    """判定一台设备的报警类别，并记录命中的物料。

    返回 (combustible, toxic, oxygen, hit) 其中 hit 是
    {类别: 命中的第一个物料名} 用于二级分组。
    """
    materials = split_media(media_str)
    combustible = toxic = oxygen = False
    hit = {}
    for m in materials:
        p = props.get(m)
        if p:
            if p['combustible'] and CLASS_COMBUSTIBLE not in hit:
                combustible = True
                hit[CLASS_COMBUSTIBLE] = m
            if p['toxic'] and CLASS_TOXIC not in hit:
                toxic = True
                hit[CLASS_TOXIC] = m
        if NITROGEN_RE.search(m) and CLASS_OXYGEN not in hit:
            oxygen = True
            hit[CLASS_OXYGEN] = m
    # 用户显式指定需氧报警的设备（离心机/耙式干燥器用氮保护但介质列未写氮）
    if get_base_tag(tag) in oxygen_tags or tag in oxygen_tags:
        oxygen = True
        hit.setdefault(CLASS_OXYGEN, '氮气(保护)')
    return combustible, toxic, oxygen, hit


# ── 标注几何参数 ──
TEXT_H = 220
LGND_H = 300
CIR_R = 180
ROW_SP = 320


def annotate(frames, tag_coords, tag_cls, out_path, title_prefix):
    doc = ezdxf.new(dxfversion='R2010')
    doc.header['$INSUNITS'] = 4
    msp = doc.modelspace()
    for lname, color in LAYER_CFG.values():
        if lname not in doc.layers:
            doc.layers.add(lname, color=color)

    for frame in frames:
        classified = {t: tag_cls[t] for t in frame['tags'] if t in tag_cls}
        if not classified:
            continue
        legend_x = frame['x_min'] + 1000
        legend_y = frame['y_max'] - 2000

        # 二级分组: 一级=类别, 二级=物料
        grouped = {c: defaultdict(list) for c in
                   (CLASS_COMBUSTIBLE, CLASS_TOXIC, CLASS_OXYGEN)}
        for tag, (comb, tox, oxy, hit) in classified.items():
            if comb:
                grouped[CLASS_COMBUSTIBLE][hit.get(CLASS_COMBUSTIBLE, '?')].append(tag)
            if tox:
                grouped[CLASS_TOXIC][hit.get(CLASS_TOXIC, '?')].append(tag)
            if oxy:
                grouped[CLASS_OXYGEN][hit.get(CLASS_OXYGEN, '?')].append(tag)

        msp.add_text(f"{title_prefix}{frame['frame_id']} 介质报警标注（类别→物料）",
                     dxfattribs={'insert': (legend_x, legend_y + 900),
                                 'height': LGND_H + 120,
                                 'layer': LAYER_CFG[CLASS_COMBUSTIBLE][0]})
        row = 0
        for disp_cls in (CLASS_COMBUSTIBLE, CLASS_TOXIC, CLASS_OXYGEN):
            materials = grouped[disp_cls]
            if not materials:
                continue
            lname = LAYER_CFG[disp_cls][0]
            total = sum(len(v) for v in materials.values())
            y1 = legend_y - row * ROW_SP
            msp.add_solid([(legend_x, y1), (legend_x + 300, y1),
                           (legend_x + 300, y1 + 300), (legend_x, y1 + 300)],
                          dxfattribs={'layer': lname})
            msp.add_text(f"【{disp_cls}】共{total}台",
                         dxfattribs={'insert': (legend_x + 420, y1 + 40),
                                     'height': TEXT_H + 90, 'layer': lname})
            row += 1
            for mname in sorted(materials.keys()):
                tags = materials[mname]
                y2 = legend_y - row * ROW_SP
                msp.add_text(f"  ● {mname}  ({len(tags)}台)",
                             dxfattribs={'insert': (legend_x + 250, y2),
                                         'height': TEXT_H + 30, 'layer': lname})
                row += 1
                tags.sort(key=lambda t: (-tag_coords[t][1], tag_coords[t][0]))
                for tag in tags:
                    ex, ey = tag_coords[tag]
                    cy = legend_y - row * ROW_SP
                    msp.add_circle((ex, ey), radius=CIR_R,
                                   dxfattribs={'layer': lname})
                    msp.add_text(f"      {tag}",
                                 dxfattribs={'insert': (legend_x + 450, cy),
                                             'height': TEXT_H, 'layer': lname})
                    msp.add_line((ex, ey), (legend_x + 400, cy + 80),
                                 dxfattribs={'layer': lname})
                    row += 1
            row += 1
        bottom = legend_y - row * ROW_SP
        if bottom < frame['y_min']:
            print(f"  ⚠ 图框{frame['frame_id']} 标注超出下边界 "
                  f"{frame['y_min'] - bottom} 单位，建议拆分或缩小行距")
        print(f"图框{frame['frame_id']}: {len(classified)}台, {row}行")

    doc.saveas(out_path)
    print(f'\n已保存: {out_path}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--frames', required=True)
    ap.add_argument('--media', required=True)
    ap.add_argument('--props', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--oxygen-tags', default='',
                    help='逗号分隔的需氧含量报警设备位号(基础位号或完整位号)')
    ap.add_argument('--title-prefix', default='图框')
    args = ap.parse_args()

    with open(args.frames, encoding='utf-8') as f:
        fd = json.load(f)
    frames, tag_coords = fd['frames'], fd['tag_coords']
    with open(args.media, encoding='utf-8') as f:
        base_media = json.load(f)
    props = load_props(args.props)
    print(f'物性表物料: {len(props)} 种  '
          f'(可燃甲乙类 {sum(1 for v in props.values() if v["combustible"])}, '
          f'有毒 {sum(1 for v in props.values() if v["toxic"])})')

    oxygen_tags = set(t.strip() for t in args.oxygen_tags.split(',') if t.strip())

    tag_cls = {}
    for tag in tag_coords:
        base = get_base_tag(tag)
        if base not in base_media:
            continue
        comb, tox, oxy, hit = classify(base_media[base], props, tag, oxygen_tags)
        if comb or tox or oxy:
            tag_cls[tag] = (comb, tox, oxy, hit)

    print(f'布置图位号: {len(tag_coords)}  已匹配设备表: '
          f'{sum(1 for t in tag_coords if get_base_tag(t) in base_media)}  '
          f'需标注: {len(tag_cls)}')
    print(f'  可燃: {sum(1 for v in tag_cls.values() if v[0])}  '
          f'有毒: {sum(1 for v in tag_cls.values() if v[1])}  '
          f'氧含量报警: {sum(1 for v in tag_cls.values() if v[2])}')

    annotate(frames, tag_coords, tag_cls, args.out, args.title_prefix)


if __name__ == '__main__':
    main()

