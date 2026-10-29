# field-survey-report

把一辆车、一双腿、一台手机拍回来的现场，变成可以直接交给下一环节的**归档成果**。

输入只有一条六只脚（foooooot）行程链接；输出三样东西：

| 产物 | 内容 |
| --- | --- |
| **A 场地调研报告（勘察结果汇编）** | 照片按 1…N 编号归档 + 索引 CSV；报告含影像台账、分区现状、问题清单（A4，公文排版） |
| **A3 现场图册** | 总图 → 分区图 → 详图三级，每页 12 张，比例尺按页自适应，300 dpi |
| **C 标注底图包（GIS）** | GeoPackage（照片点位/踏勘轨迹/待圈定范围三层）+ QGIS 工程 + 带编号 KML + 打开说明；点位自带编号样式，可直接删点、筛点、圈范围 |

## 边界（重要）

本 skill 只做**记录、归档、分类**。不做场地评价、不做前期文件逐条对照、不出改造或设计建议——那些属于 Project Research 与后续会议阶段。

原因见 SKILL.md「为什么本 skill 不做分析与建议」：现场照片是抽样不是普查，据此下全称判断（"全园只有一处导览图"）会得到断章取义的结论。报告里所有描述必须限定在"现场所见范围"。

## 依赖

| 组件 | 用途 |
| --- | --- |
| QGIS 3.44 + 无头运行器 | 图册底图、路线图、标注底图包（GPKG/QGZ） |
| Python 3.11+（Pillow、PyMuPDF） | 图像处理、A3 合版、PDF 合并 |
| [gongwen-docx](../gongwen-docx) | 报告排版（GB/T 9704 公文格式） |

## 用法

```bash
# 1 抓行程（轨迹四格式 + 原始照片）
python scripts/fetch_field_data.py --trip <行程号> --out <目录>

# 2 照片归档重命名 + 索引
python scripts/archive_photos.py --meta <meta.json> --photo-dir <原图目录> \
    --out-dir 照片归档 --footprints <脚印.json> --strip-prefix P

# 3 A3 图册（自动分页 + 三级底图 + 合版，只留最终 PDF）
python scripts/build_album.py --config album_config.json

# 4 标注底图包（GPKG / QGZ / KML / 打开说明）
D:\QGIS_PROJ\_tooling\run_pyqgis.cmd scripts/build_gis_package.py \
    --meta 照片归档/meta_archived.json --gpx 轨迹/xxx.gpx \
    --out-dir 01_现场/标注 --title "项目名_现场标注" \
    --report "02_调研报告/报告/项目名_场地调研报告.md"

# 5 报告路线图
D:\QGIS_PROJ\_tooling\run_pyqgis.cmd scripts/qgis_render_track.py --track <原始轨迹.json> --out map.png
python scripts/decorate_map.py --in map.png --out 路线图.png

# 6 排版（gongwen-docx）→ 插图 → 渲染校对
python ../gongwen-docx/scripts/gongwen.py 报告.md 报告.docx
python scripts/insert_images.py --docx 报告.docx --base-dir .
python ../gongwen-docx/scripts/render_check.py 报告.docx --png 1,2
```

## 目录

```
SKILL.md                     总说明（流程 / 硬规则 / 常见故障 / 变更记录）
references/
  场地调研报告模板.md         报告章节模板（含抽样原则）
  report-template.md          模板索引
  field-data.md               六只脚抓取接口
  album-config.example.json   一键图册参数样例
scripts/
  fetch_field_data.py         抓取行程 + 转 KML/GPX/PLT + 下载原图
  archive_photos.py           照片归档重命名 + 照片索引.csv + meta_archived.json
  build_album.py              一键 A3 图册（分页 + 底图 + 合版 + 最终 PDF）
  qgis_render_album_maps.py   三级底图渲染（总图/分区图/详图）
  compose_album_a3.py         A3 横排合版（12 张 + 反索引 + 编号）
  build_gis_package.py        标注底图包（GPKG/QGZ/KML/QML/打开说明）
  qgis_render_track.py        报告用轨迹图渲染
  decorate_map.py             标题卡/图例/比例尺/指北针
  insert_images.py            DOCX 按 @@IMG:文件名|宽cm@@ 插图
```

## 项目库约定

产物按目录归档，不重复存放：

```
项目库/{项目名}/
├── 00_资料收集/     案头资料、外部调研成果（只此一处）
├── 01_现场/         轨迹 · 照片归档 · 标注/（GIS 底图包）
└── 02_调研报告/     制图/（图册、路线图） · 报告/（产物 A）
```

## 版本

当前 **v1.6**（2026-10-28）。主要演进：

- v1.6 标注包：样式写进 GPKG 本体（编号直接可见）、生成 `00_打开说明.txt`、工程存相对路径
- v1.5 退役件管理办法：skill 内只放活件，停用文件移出并在外部归档区登记
- v1.4 撤掉「项目前期报告」产物，新增抽样原则（禁止全称判断）
- v1.3 报告边界收紧（删设计建议、去掉对照表"处置建议"列）
- v1.2 新增标注底图包；修照片抓取无扩展名 URL、图册比例尺档位
- v1.1 图册自适应（详图按页取范围、总图随线路走向）
