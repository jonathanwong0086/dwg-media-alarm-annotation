# -*- coding: utf-8 -*-
"""设备布置图介质报警标注 —— 共用函数库

所有脚本共享的基础能力：位号解析、图框标准尺寸、介质分词。
不含任何客户数据。
"""
import re

# ────────────────────────────────────────────────────────────
# 位号（设备 tag）解析
# ────────────────────────────────────────────────────────────
# 布置图/设备表位号形如：R1001、P1001A、P1001AB、V1001C、DR2001A、P1001A~C、P1001A/B
# 前缀 1~3 位字母 + 4 位数字 + 0~4 位尾缀（字母及范围符号 ~ - /）
TAG_PATTERN = re.compile(r'^[A-Z]{1,3}\d{4}[A-Z]{0,4}$')
# 设备表里的组合位号可能带范围/斜杠符号（P5202A~C、P1001A/B），单独放宽
TAG_PATTERN_LOOSE = re.compile(r'^[A-Z]{1,3}\d{4}[A-Z~\-/]{0,6}$')

# 尾缀允许出现的字符（多台设备编号 A/B/C、范围 A~C、斜杠 A/B）
_SUFFIX_RE = re.compile(r'[A-Z/~\-]+$')


def get_base_tag(tag):
    """去掉尾部字母/范围符号，得到设备系列基础位号。

    P1001A   -> P1001
    P1001AB  -> P1001
    R1001ABCD-> R1001
    P1001A~C -> P1001
    V3001C   -> V3001
    """
    return _SUFFIX_RE.sub('', str(tag).strip())


def is_equipment_tag(text, loose=False):
    """判断一段文字是否是设备位号。

    loose=True 时接受设备表中的组合写法（P5202A~C、P1001A/B）。
    """
    s = str(text).strip()
    if loose:
        return bool(TAG_PATTERN_LOOSE.match(s))
    return bool(TAG_PATTERN.match(s))


# ────────────────────────────────────────────────────────────
# 介质字符串分词
# ────────────────────────────────────────────────────────────
_MEDIA_SPLIT_RE = re.compile(r'[、，,；;/\s]+')


def split_media(media_str):
    """把介质列文本拆成单个物料名列表。

    '甲苯、DMF、水' -> ['甲苯', 'DMF', '水']
    """
    if not media_str:
        return []
    return [p.strip() for p in _MEDIA_SPLIT_RE.split(str(media_str)) if p.strip()]


# ────────────────────────────────────────────────────────────
# TK*** 图框标准尺寸表（1:100 比例，单位=图纸mm×100）
# ────────────────────────────────────────────────────────────
# 命名规范：TK[系列][朝向][加长]
#   系列: 1=A1  2=A2  3=A3
#   朝向: L=横放(long)  H=竖放(high)
#   加长: A=原尺寸  B=+1/4长边  C=+1/2长边
# A1 长边=841mm 短边=594mm；加长作用在长边上。
# 尺寸以 (宽, 高) 给出，需结合图框块的实际摆放朝向再判定。
_A_SERIES_LONG = {1: 841, 2: 594, 3: 420}   # A1/A2/A3 长边(mm)
_A_SERIES_SHORT = {1: 594, 2: 420, 3: 297}  # A1/A2/A3 短边(mm)
_EXTEND_FACTOR = {'A': 0.0, 'B': 0.25, 'C': 0.5}


def parse_tk_name(name, scale=100):
    """解析 TK 图框块名，返回该图框在模型空间的两种候选尺寸 (mm×scale)。

    因为图框块本身不携带朝向信息，返回横放/竖放两组尺寸，
    由 detect_frames 用"零重叠且全覆盖"准则选出正确朝向。

    返回: dict 或 None
      {
        'series': 1, 'orient': 'L', 'extend': 'A',
        'long': 84100, 'short': 59400,
        'landscape': (84100, 59400),  # (宽, 高)
        'portrait':  (59400, 84100),
      }
    """
    m = re.match(r'^TK([123])([LH])([ABC])$', str(name).strip())
    if not m:
        return None
    series = int(m.group(1))
    orient = m.group(2)
    extend = m.group(3)
    long_mm = _A_SERIES_LONG[series] * (1 + _EXTEND_FACTOR[extend])
    short_mm = _A_SERIES_SHORT[series]
    long_u = round(long_mm * scale)
    short_u = round(short_mm * scale)
    return {
        'series': series, 'orient': orient, 'extend': extend,
        'long': long_u, 'short': short_u,
        'landscape': (long_u, short_u),   # 长边水平
        'portrait': (short_u, long_u),    # 长边竖直
    }


# ────────────────────────────────────────────────────────────
# 报警类别常量
# ────────────────────────────────────────────────────────────
CLASS_COMBUSTIBLE = '可燃'
CLASS_TOXIC = '有毒'
CLASS_OXYGEN = '氧含量报警'
CLASS_ORDER = {CLASS_COMBUSTIBLE: 0, CLASS_TOXIC: 1, CLASS_OXYGEN: 2}

# DXF 图层配置：(层名, AutoCAD 颜色号)
LAYER_CFG = {
    CLASS_COMBUSTIBLE: ('ANNOT_COMBUSTIBLE', 1),   # 红
    CLASS_TOXIC: ('ANNOT_TOXIC', 6),               # 品红
    CLASS_OXYGEN: ('ANNOT_OXYGEN', 30),            # 橙
}

# 可燃判定：火灾危险性类别属于甲类或乙类（GB 50016-2014 表3.1.1）
COMBUSTIBLE_FIRE_CLASSES = {'甲', '甲类', '乙', '乙类'}


def is_combustible_fire_class(fire_class):
    """火灾危险性类别文本 -> 是否属于可燃标注范围（甲类/乙类）。"""
    if not fire_class:
        return False
    s = str(fire_class).strip()
    return any(k in s for k in ('甲', '乙')) and '非' not in s
