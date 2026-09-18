# dwg-media-alarm-annotation

为化工设备布置图(DWG/DXF)按介质危害自动标注三类报警的 Claude Skill：
**可燃(甲/乙类)、有毒、氧含量报警**。

按 `TK***` 图框分区，二级分组(类别→物料→设备)标注在图框四角内，不跨图框。
介质列灵活识别不写死；可燃范围由 [chem-properties-excel](https://github.com/jonathanwong0086/chem-properties-excel)
生成的物性表(火灾危险性类别列)驱动。

## 分类规则

| 报警类别 | 判定依据 | 数据来源 |
|----------|----------|----------|
| **可燃** | 介质中任一物料的火灾危险性类别为甲类或乙类 (GB 50016-2014) | 物性表"火灾危险性类别"列 |
| **有毒** | 介质中任一物料被列入有毒气体检测目录 | 物性表"是否被列入有毒气体检测目录"列 |
| **氧含量报警** | 介质含"氮/N2"，或用户显式指定 | 介质列 + `--oxygen-tags` |

## 用法

```bash
# 1. 图纸识别：DWG→DXF + 图框/位号识别 + 朝向自动判定
python scripts/detect_frames.py "layout.dwg" --out _frames.json

# 2. 设备表读取：灵活识别介质列 → 基础位号→介质映射
python scripts/read_equipment.py "equipment-list.xlsx" --out base_media.json

# 3+4. 分类与标注：读物性表判定，二级分组标注
python scripts/annotate.py --frames _frames.json --media base_media.json \
    --props "properties.xlsx" --out "layout_标注.dxf" \
    [--oxygen-tags C1001,DR2001]
```

详见 [SKILL.md](SKILL.md)、[examples/example-run.md](examples/example-run.md)。

## 依赖

- Python: `ezdxf`, `openpyxl`
- [ODA File Converter](https://www.opendesign.com/guestfiles/oda_file_converter)（DWG→DXF，仅当输入是 DWG）
- 前置：先用 chem-properties-excel 生成物性表

## 结构

```
SKILL.md                      触发条件 + 5步流程 + 分类规则
scripts/lib.py                共用：位号解析/TK图框尺寸/介质分词/可燃判定
scripts/detect_frames.py      图框识别 + 朝向自动判定
scripts/read_equipment.py     设备表灵活列识别
scripts/annotate.py           分类 + 二级分组标注
reference/                    TK尺寸表、分类规则
examples/                     完整命令示例(匿名数据)
```

## License

MIT
