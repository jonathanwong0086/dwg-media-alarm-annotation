# -*- coding: utf-8 -*-
"""图纸识别 —— DWG→DXF(ODA) + TK 图框识别 + 位号提取 + 朝向自动判定。

用法:
  python detect_frames.py <图纸.dwg 或 .dxf> [--out _frames.json] [--scale 100]
                          [--oda "C:/Program Files/ODA/ODAFileConverter 27.1.0"]

输出 _frames.json:
  {
    "frames": [{frame_id, tk_name, x_min, x_max, y_min, y_max,
                tags:[...],                    # 去重后的位号列表
                instances:[[tag, x, y], ...]}  # 每次出现（含跨楼层重复）
               ...],
    "tag_coords": {tag: [[x, y], ...], ...},   # 同一位号可能出现在多处
    "orientation": "landscape" | "portrait"
  }

跨楼层设备说明: 同一设备位号可能出现在多个图框内（体现在图里就是
位号在不同图框各画一次）。tag_coords 用坐标列表保留全部出现位置，
frames[*].instances 记录每次出现，标注脚本据此在每个图框逐次标注。
"""
import sys
import os
import re
import json
import glob
import shutil
import argparse
import subprocess
import tempfile

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import is_equipment_tag, parse_tk_name  # noqa: E402

import ezdxf  # noqa: E402

TK_NAME_RE = re.compile(r'^TK[123][LH][ABC]$')
DEFAULT_ODA = r'C:/Program Files/ODA/ODAFileConverter 27.1.0'


def convert_dwg_to_dxf(dwg_path, oda_dir):
    """用 ODA File Converter 把单个 DWG 转成 DXF，返回 dxf 路径。"""
    exe = os.path.join(oda_dir, 'ODAFileConverter.exe')
    if not os.path.exists(exe):
        raise FileNotFoundError(f'未找到 ODA 转换器: {exe}')
    in_dir = tempfile.mkdtemp(prefix='oda_in_')
    out_dir = tempfile.mkdtemp(prefix='oda_out_')
    shutil.copy2(dwg_path, os.path.join(in_dir, 'x.dwg'))
    # 参数: 输入目录 输出目录 输出版本 输出格式 递归(0) 审计(1)
    subprocess.run([exe, in_dir, out_dir, 'ACAD2010', 'DXF', '0', '1'],
                   timeout=600, check=False)
    outs = glob.glob(os.path.join(out_dir, '*.dxf'))
    if not outs:
        raise RuntimeError('ODA 转换失败，未生成 DXF（可尝试 ACAD2018 版本）')
    return outs[0]


def extract(dxf_path, scale):
    """从 DXF 提取 TK 图框块位置 + 设备位号坐标。"""
    doc = ezdxf.readfile(dxf_path)
    msp = doc.modelspace()

    tks = []
    for ent in msp.query('INSERT'):
        name = ent.dxf.name
        if TK_NAME_RE.match(name):
            tks.append((name, round(ent.dxf.insert.x), round(ent.dxf.insert.y)))

    # 保留同一位号的全部出现位置（跨楼层设备会出现多次）
    tag_coords = {}
    for ent in msp.query('TEXT MTEXT'):
        text = ent.dxf.text if ent.dxftype() == 'TEXT' else ent.text
        text = text.strip()
        if is_equipment_tag(text):
            p = ent.dxf.insert
            tag_coords.setdefault(text, []).append((round(p.x), round(p.y)))
    return tks, tag_coords


def assign(tks, tag_coords, orient, scale):
    """给定朝向，把位号分配到各图框，返回 (frames, covered, overlap)。

    TK 图框块位于图框左下角，尺寸由 parse_tk_name 的标准尺寸给出。
    每个出现位置(instance)独立判定归属；同一位号的多次出现可分属不同
    图框（跨楼层），也可能落在同一图框（同层多处）。

    - covered: 落入任意图框的出现次数（越多越好）
    - overlap: 一次出现同时落进多个图框的次数（图框重叠/尺寸判错，越少越好）
    """
    frames = []
    for i, (name, bx, by) in enumerate(sorted(tks, key=lambda t: (t[2], t[1])), 1):
        dims = parse_tk_name(name, scale)
        W, H = dims[orient]
        x_min, x_max = bx, bx + W
        y_min, y_max = by, by + H
        instances = []
        for t, coords in tag_coords.items():
            for (x, y) in coords:
                if x_min <= x <= x_max and y_min <= y <= y_max:
                    instances.append([t, x, y])
        # 去重后的位号列表，保持首次出现顺序
        tags = list(dict.fromkeys(inst[0] for inst in instances))
        frames.append({'frame_id': i, 'tk_name': name,
                       'x_min': x_min, 'x_max': x_max,
                       'y_min': y_min, 'y_max': y_max,
                       'tags': tags, 'instances': instances})

    # 统计每个 (tag, x, y) 出现位置命中了几个图框
    hit = {}
    for f in frames:
        for t, x, y in f['instances']:
            key = (t, x, y)
            hit[key] = hit.get(key, 0) + 1
    covered = len(hit)
    overlap = sum(1 for v in hit.values() if v > 1)
    return frames, covered, overlap


def choose_orientation(tks, tag_coords, scale):
    """测试横放/竖放，选"覆盖最全且重叠最少"的朝向。"""
    best = None
    for orient in ('landscape', 'portrait'):
        frames, covered, overlap = assign(tks, tag_coords, orient, scale)
        # 评分：优先零重叠(图框不该互相盖住)，其次覆盖最多。
        score = covered - overlap * 1000
        if best is None or score > best[0]:
            best = (score, orient, frames, covered, overlap)
    return best[1], best[2], best[3], best[4]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('drawing')
    ap.add_argument('--out', default='_frames.json')
    ap.add_argument('--scale', type=int, default=100)
    ap.add_argument('--oda', default=DEFAULT_ODA)
    args = ap.parse_args()

    path = args.drawing
    if path.lower().endswith('.dwg'):
        print('转换 DWG → DXF ...')
        path = convert_dwg_to_dxf(path, args.oda)
        print(f'  已转换: {path}')

    tks, tag_coords = extract(path, args.scale)
    total_inst = sum(len(v) for v in tag_coords.values())
    print(f'TK 图框块: {len(tks)} 个')
    for name, x, y in sorted(tks, key=lambda t: (t[2], t[1])):
        print(f'  {name} @ ({x}, {y})')
    print(f'设备位号: {len(tag_coords)} 个（出现 {total_inst} 次，含跨楼层重复）')

    if not tks:
        print('警告: 未找到 TK 图框块，无法分区。')
        return

    orient, frames, covered, overlap = choose_orientation(tks, tag_coords, args.scale)
    print(f'\n判定朝向: {orient}  覆盖: {covered}/{total_inst} 次  重叠: {overlap}')
    for f in frames:
        n_inst = len(f['instances'])
        extra = f'（{n_inst} 处）' if n_inst != len(f['tags']) else ''
        print(f"  图框{f['frame_id']} [{f['tk_name']}]: {len(f['tags'])} 台{extra}")

    with open(args.out, 'w', encoding='utf-8') as fp:
        json.dump({'frames': frames, 'tag_coords': tag_coords,
                   'orientation': orient}, fp, ensure_ascii=False, indent=2)
    print(f'\n已写入: {args.out}')


if __name__ == '__main__':
    main()
