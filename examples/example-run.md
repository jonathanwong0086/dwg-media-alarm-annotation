# 示例：完整标注流程

> 本示例使用**匿名占位数据**（虚构位号、通用路径），不含任何客户或项目信息。
> 实际使用时替换为你的文件路径。

## 场景

一张设备布置图 `layout.dwg`，含 4 个 A1 横放图框(TK1LA)，约 380 台设备。
已备好设备一览表 `equipment-list.xlsx` 和化学品物性表 `properties.xlsx`。

## Step 0 · 前置检查

```bash
# 确认有物性表(含"火灾危险性类别"列)
ls *物性*.xlsx *properties*.xlsx
```
找不到 → 先跑 chem-properties-excel skill 生成。
文件在加密网盘 → 先用 decryptor-cli 解密。

## Step 1 · 图纸识别

```bash
python scripts/detect_frames.py "layout.dwg" --out _frames.json
```

预期输出（示意）：
```
转换 DWG → DXF ...
TK 图框块: 4 个
  TK1LA @ (X0, Y0)
  ...
设备位号: 380 个
判定朝向: landscape  分配: 380/380  重复: 0
  图框1 [TK1LA]: 100 台
  ...
已写入: _frames.json
```

朝向被自动判定为 landscape（全覆盖零重叠）。若分配数 < 总数或有重复，
检查图框块名与 TK 尺寸表是否匹配。

## Step 2 · 设备表读取

```bash
python scripts/read_equipment.py "equipment-list.xlsx" --out base_media.json
```

预期输出（示意）：
```
设备表: equipment-list.xlsx
  [反应釜类...] 20 台
  [储罐类...] 70 台
  [换热器类...] 65 台   ← 壳程/管程双介质已合并
  [机泵类...] 80 台
  [其他类...] 60 台
基础位号合计: 300 个
已写入: base_media.json
```

## Step 3+4 · 分类与标注

```bash
python scripts/annotate.py \
    --frames _frames.json \
    --media base_media.json \
    --props "properties.xlsx" \
    --out "layout_标注.dxf"
```

若某些离心机/干燥器需氧含量报警（介质列没写氮气）：
```bash
python scripts/annotate.py ... --oxygen-tags AAA0001,BBB0002
```

预期输出（示意）：
```
物性表物料: 40 种  (可燃甲乙类 15, 有毒 8)
布置图位号: 380  已匹配设备表: 379  需标注: 285
  可燃: 280  有毒: 77  氧含量报警: 0
图框1: 73台, 102行
...
已保存: layout_标注.dxf
```

出现 `⚠ 图框N 标注超出下边界` 时，说明该图框设备太多，
标注列超出四角范围 —— 需减小行距或考虑该图框换更大幅面。

## Step 5 · 交付

用 CAD 打开确认标注都在图框内后，复制到项目目录。
中文/加密盘路径用 Python `shutil.copy2` 处理，避免 shell 转义问题。

## 常见问题

- **未匹配位号**：布置图有、设备表无 → 该设备在设备表里确实缺失(数据缺口)，非脚本问题
- **可燃数偏少**：物性表火灾类别列可能有"丙类/非可燃"，符合预期(丙类不标可燃)
- **氧含量报警为0**：默认只认介质含氮；需要就用 `--oxygen-tags` 指定
- **DWG 转换失败**：ODA 报 "Invalid group code" → 换 `ACAD2018` 版本重试，或让用户另存图纸
