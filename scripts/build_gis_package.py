#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成「现场标注底图包」：GeoPackage + QGIS 工程 + 带编号 KML（field-survey-report skill）

为什么不是只给 KML：KML 在 QGIS 里是只读图层，选得中、删不掉。
现场标注的真实用途是「按编号挑拣 / 删点 / 接着圈范围」，必须在可编辑矢量图层上做，
所以数据落 GeoPackage，KML 只承担"看得见、发得出去"。

必须在 QGIS 环境下运行（无头）：
    D:\\QGIS_PROJ\\_tooling\\run_pyqgis.cmd build_gis_package.py \\
        --meta 照片归档/meta_archived.json \\
        --gpx 轨迹/xxxx.gpx \\
        --out-dir 01_现场/标注 \\
        --title "恩平百兽园_现场标注" \\
        --report "02_调研报告/报告/xxx_场地调研报告.md" \\
        --basemap esri

产物（写入 out-dir）：
    {title}.gpkg                 三层：照片点位(POINT) / 踏勘轨迹(LINESTRING) / 项目库范围(POLYGON，空)
    {title}.qgz                  QGIS 工程：影像底图 + 三层 + 编号标注 + 打开即定位
    {title}_照片点位_编号.kml     给 Google Earth / 手机 / 外业看
    {title}_轨迹与点位_合并.kml   轨迹与点位同一文件
    自检_点位分布.jpg            几何与底图自检（带编号渲染；无字体时自动降级提醒）

照片点位字段：
    编号 int · 文件名 · 拍摄时间 · 经度 · 纬度 · 画面内容 · 坐标备注 · 保留
「保留」默认全 1：讨论后把要去掉的置 0，比直接删更好回溯。

坐标备注自动判读两条（都是六只脚数据的老问题）：
    1) 坐标 == 轨迹首点 且 拍摄时间早于轨迹开始 → 「起点补齐」——照片在开记录前拍的，
       六只脚把坐标补成了起点，图上会重合在起点；
    2) 与他点坐标完全相同 → 「坐标与他点重合（编号…）」——同一处连拍或一次上传共用一次定位。
"""
import argparse
import json
import math
import os
import re
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict

from qgis.core import (
    QgsVectorLayer, QgsField, QgsFeature, QgsGeometry, QgsPointXY, QgsProject,
    QgsVectorFileWriter, QgsCoordinateReferenceSystem, QgsCoordinateTransform,
    QgsRectangle, QgsMapSettings, QgsMapRendererParallelJob, QgsRasterLayer,
    QgsPalLayerSettings, QgsTextFormat, QgsTextBufferSettings,
    QgsVectorLayerSimpleLabeling, QgsMarkerSymbol, QgsLineSymbol, QgsFillSymbol,
    QgsSingleSymbolRenderer, QgsReferencedRectangle,
)
from qgis.PyQt.QtGui import QColor, QFont, QFontDatabase
from qgis.PyQt.QtCore import QSize, QVariant

BASEMAPS = {
    "esri": ("Esri World Imagery",
             "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/"
             "MapServer/tile/{z}/{y}/{x}"),
    "google": ("Google 卫星",
               "https://mt1.google.com/vt/lyrs%3Ds%26x={x}%26y={y}%26z={z}"),
}

DESC_RE = re.compile(r'^\|\s*(\d+)\s*\|\s*([^|]+?)\s*\|\s*([^|]*?)\s*\|\s*([^|]*?)\s*\|\s*([^|]*?)\s*\|\s*$')


def load_font(size=8):
    """给无头渲染装上中文字体，否则标注会渲染成方框（Qt 自带字体目录通常为空）。"""
    for p in (r'C:\Windows\Fonts\msyh.ttc', r'C:\Windows\Fonts\simhei.ttf',
              r'/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc'):
        if os.path.exists(p):
            QFontDatabase.addApplicationFont(p)
    f = QFont('Microsoft YaHei')
    f.setPointSize(size)
    return f


def read_descriptions(path):
    """从《场地调研报告》的影像台账表里取「画面内容」，保证底图文字与报告同源。"""
    if not path or not os.path.exists(path):
        return {}
    out = {}
    for line in open(path, encoding='utf-8'):
        m = DESC_RE.match(line.strip())
        if m:
            txt = m.group(5).strip()
            if txt and not txt.startswith('---'):
                out[int(m.group(1))] = txt
    return out


def gpx_points(path):
    root = ET.parse(path).getroot()
    pts, times = [], []
    for p in root.iter('{http://www.topografix.com/GPX/1/1}trkpt'):
        pts.append((float(p.get('lat')), float(p.get('lon'))))
        t = p.find('{http://www.topografix.com/GPX/1/1}time')
        times.append(t.text if t is not None else '')
    return pts, times


def track_stats(pts, times):
    """里程（km）与用时（h）：六只脚导出的 GPX 不带统计数据，现场算。"""
    dist = 0.0
    for (la1, lo1), (la2, lo2) in zip(pts, pts[1:]):
        dlat = math.radians(la2 - la1)
        dlon = math.radians(lo2 - lo1)
        h = (math.sin(dlat / 2) ** 2
             + math.cos(math.radians(la1)) * math.cos(math.radians(la2)) * math.sin(dlon / 2) ** 2)
        dist += 2 * 6371000.0 * math.asin(math.sqrt(h))
    dur = 0.0
    try:
        import datetime
        t0 = datetime.datetime.fromisoformat(times[0].replace('Z', '+00:00'))
        t1 = datetime.datetime.fromisoformat(times[-1].replace('Z', '+00:00'))
        dur = (t1 - t0).total_seconds() / 3600.0
    except Exception:
        pass
    return dist / 1000.0, dur


def build_layers(meta, desc, track_pts, track_times, area_name):
    def new_layer(wkb, name, extra):
        lyr = QgsVectorLayer('%s?crs=EPSG:4326&field=编号:integer' % wkb, name, 'memory')
        lyr.dataProvider().addAttributes(
            [QgsField(n, t, len=ln) if t == QVariant.String else QgsField(n, t)
             for n, t, ln in extra])
        lyr.updateFields()
        return lyr

    # 坐标质量判读
    start = (round(track_pts[0][0], 6), round(track_pts[0][1], 6))
    t0 = track_times[0] if track_times else ''
    groups = defaultdict(list)
    for m in meta:
        groups[(round(float(m['lat']), 6), round(float(m['lon']), 6))].append(m['seq'])

    def note(m):
        key = (round(float(m['lat']), 6), round(float(m['lon']), 6))
        if key == start and t0 and str(m.get('time', '')) and str(m['time']) < t0:
            return '起点补齐：早于轨迹开始，实际位置在起点附近'
        if len(groups[key]) > 1:
            others = [s for s in groups[key] if s != m['seq']]
            return '坐标与他点重合（%s）' % '、'.join(str(x) for x in others[:4])
        return ''

    pts = new_layer('Point', '照片点位', [
        ('文件名', QVariant.String, 24), ('拍摄时间', QVariant.String, 24),
        ('经度', QVariant.Double, 24), ('纬度', QVariant.Double, 24),
        ('画面内容', QVariant.String, 120), ('坐标备注', QVariant.String, 80),
        ('保留', QVariant.Int, 24)])
    feats = []
    for m in meta:
        f = QgsFeature(pts.fields())
        f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(float(m['lon']), float(m['lat']))))
        f.setAttributes([m['seq'], m['file'], m.get('time', ''),
                         round(float(m['lon']), 6), round(float(m['lat']), 6),
                         desc.get(m['seq'], ''), note(m), 1])
        feats.append(f)
    pts.dataProvider().addFeatures(feats)
    pts.updateExtents()

    trk = new_layer('LineString', '踏勘轨迹', [
        ('里程_km', QVariant.Double, 24), ('用时_h', QVariant.Double, 24)])
    ft = QgsFeature(trk.fields())
    ft.setGeometry(QgsGeometry.fromPolylineXY([QgsPointXY(lo, la) for la, lo in track_pts]))
    km, hrs = track_stats(track_pts, track_times)
    ft.setAttributes([1, round(km, 3), round(hrs, 3)])
    trk.dataProvider().addFeature(ft)
    trk.updateExtents()
    print('轨迹 %.3f km / %.2f h' % (km, hrs))

    area = new_layer('Polygon', area_name, [('名称', QVariant.String, 60),
                                            ('备注', QVariant.String, 120)])
    return pts, trk, area


def embed_default_styles(gpkg, area_name, label_size, out_dir):
    """把图层样式写进 GPKG 的 layer_styles 表（useAsDefault=1），并导出一份 QML 备用。

    为什么必须做：标注样式原本只存在于 .qgz 工程里。用户直接打开 .gpkg（很多人就是直接
    拖 gpkg 进来）时，点位只有圆点、没有编号，跟照片命名对不上——2026-10-28 实际踩到。
    写进 layer_styles 之后，任何人加载这个 GPKG 图层都会自动带上编号标注。
    """
    style_names = {'照片点位': '编号标注', '踏勘轨迹': '轨迹红线'}
    specs = [
        ('照片点位', QgsMarkerSymbol.createSimple({
            'name': 'circle', 'color': '0,150,200,255', 'size': '2.0',
            'outline_color': '255,255,255,255', 'outline_width': '0.3'}), True),
        ('踏勘轨迹', QgsLineSymbol.createSimple({
            'color': '230,30,40,255', 'width': '0.9',
            'capstyle': 'round', 'joinstyle': 'round'}), False),
        (area_name, QgsFillSymbol.createSimple({
            'color': '255,170,0,40', 'outline_color': '255,140,0,255',
            'outline_width': '0.8', 'outline_style': 'dash'}), False),
    ]
    for name, sym, is_point in specs:
        lyr = QgsVectorLayer('%s|layername=%s' % (gpkg, name), name, 'ogr')
        if not lyr.isValid():
            print('WARN 样式跳过（图层打不开）：', name)
            continue
        lyr.setRenderer(QgsSingleSymbolRenderer(sym))
        if is_point:
            pal = QgsPalLayerSettings()
            pal.fieldName = '编号'
            pal.isExpression = False
            try:
                pal.placement = QgsPalLayerSettings.LabelPlacement.OverPoint
            except Exception:
                try:
                    pal.placement = QgsPalLayerSettings.OverPoint
                except Exception:
                    pass
            fmt = QgsTextFormat()
            fmt.setFont(load_font(label_size))
            fmt.setSize(label_size)
            fmt.setColor(QColor(0, 70, 140))
            buf = QgsTextBufferSettings()
            buf.setEnabled(True)
            buf.setSize(1.0)
            buf.setColor(QColor(255, 255, 255))
            fmt.setBuffer(buf)
            pal.setFormat(fmt)
            try:
                pal.displayAll = True
                pal.obstacle = False
            except Exception:
                pass
            lyr.setLabeling(QgsVectorLayerSimpleLabeling(pal))
            lyr.setLabelsEnabled(True)
            # 备用：别的 GPKG 副本或别人机器上可手动「加载样式」
            lyr.saveNamedStyle(os.path.join(out_dir, '照片点位_编号标注.qml'))
        lyr.saveStyleToDatabase(style_names.get(name, name), '默认样式（自动套用）', True, '')
        print('style embedded:', name)



def write_open_note(out_dir, title, n_points, area_name):
    """给非 GIS 同事的入口说明。面对一堆 .qgz/.gpkg/.kml，多数人第一反应是"点哪个"。"""
    txt = """{title} · 现场标注包 · 打开说明
================================================

这个文件夹里的文件，记三条就够。

一、想看图：双击「{title}.qgz」
    会打开 QGIS，自动加载底图、{n} 个编号点位、踏勘轨迹和范围图层。
    前提：qgz 和 gpkg 必须在同一个文件夹里。整个文件夹可以整体拷走、改名、发给别人。

二、所有数据只在「{title}.gpkg」这一个文件里
    三个图层：照片点位（{n} 个编号点）、踏勘轨迹、{area}（空层）。
    删点、按编号筛选、画范围，都在这个文件上改。
    备份：只拷 gpkg。发人：gpkg + qgz 一起发。
    用 ArcGIS 的同事：只发 gpkg（ArcGIS 打不开 qgz）；打开后把标注字段设成「编号」，才有编号。

三、其余是配套和备查
    *_照片点位_编号.kml   给 Google Earth / 手机 / 外业看，只读
    *_轨迹与点位_合并.kml 轨迹与点位合一的版本
    照片点位_编号标注.qml  样式备份，正常用不到
    自检_点位分布.png     出图自检截图，不是数据
    README/打开说明        字段、坐标系、精度、常见问题

编号怎么对照片
    地图上点编号 -> 属性表里该行的「文件名」就是照片归档里的文件名（如 5_p005.jpg）。
    完整对照表在 照片归档/照片索引.csv（编号、归档文件名、原文件名、时间、经纬度）。

出问题先看
    图层前面有红色感叹号 = qgz 与 gpkg 没放一起，或 gpkg 被改名了。
    看不到编号 = 图层右键「重新加载」；或在图层属性里加载 照片点位_编号标注.qml。
""".format(title=title, n=n_points, area=area_name)
    p = os.path.join(out_dir, '00_打开说明.txt')
    open(p, 'w', encoding='utf-8').write(txt)
    print('note ->', p)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--meta', required=True, help='归档后的 meta_archived.json')
    ap.add_argument('--gpx', required=True, help='踏勘轨迹 GPX（WGS84）')
    ap.add_argument('--out-dir', required=True, help='产物目录')
    ap.add_argument('--title', default='现场标注', help='产物文件名前缀，如 恩平百兽园_现场标注')
    ap.add_argument('--report', default='',
                    help='可选：场地调研报告 md，用于取「画面内容」，与报告同源')
    ap.add_argument('--basemap', default='esri', choices=sorted(BASEMAPS))
    ap.add_argument('--project-crs', default='EPSG:3857',
                    help='工程显示 CRS；出图前可改 CGCS2000 3 度带（见脚本末尾提示）')
    ap.add_argument('--area-name', default='项目库范围（待圈定）')
    ap.add_argument('--label-size', type=int, default=8)
    ap.add_argument('--skip-render', action='store_true')
    a = ap.parse_args()

    out = os.path.abspath(a.out_dir)
    os.makedirs(out, exist_ok=True)
    gpkg = os.path.join(out, a.title + '.gpkg')
    qgz = os.path.join(out, a.title + '.qgz')
    if os.path.exists(gpkg):
        os.remove(gpkg)

    meta = json.load(open(a.meta, encoding='utf-8'))
    meta = sorted(meta, key=lambda m: m.get('seq', 0))
    desc = read_descriptions(a.report)
    track_pts, track_times = gpx_points(a.gpx)
    print('meta %d 点，轨迹 %d 点，画面内容 %d 条' % (len(meta), len(track_pts), len(desc)))

    pts, trk, area = build_layers(meta, desc, track_pts, track_times, a.area_name)

    # --- GPKG：第一层覆盖建库，其后逐层追加
    for i, lyr in enumerate((pts, trk, area)):
        opt = QgsVectorFileWriter.SaveVectorOptions()
        opt.driverName = 'GPKG'
        opt.layerName = lyr.name()
        opt.fileEncoding = 'UTF-8'
        opt.actionOnExistingFile = (QgsVectorFileWriter.CreateOrOverwriteFile if i == 0
                                    else QgsVectorFileWriter.CreateOrOverwriteLayer)
        res = QgsVectorFileWriter.writeAsVectorFormatV3(
            lyr, gpkg, QgsProject.instance().transformContext(), opt)
        if res[0] != QgsVectorFileWriter.NoError:
            raise SystemExit('写 GPKG 失败：%s %s' % (lyr.name(), res[1]))

    # --- 把样式写进 GPKG 本体（layer_styles，useAsDefault=1）
    # 否则用户直接打开 .gpkg（不经过 .qgz）时，点位只是圆点、没有编号，对不上照片命名。
    embed_default_styles(gpkg, a.area_name, a.label_size, out)

    # --- QGIS 工程
    proj = QgsProject.instance()
    proj.clear()
    proj.setCrs(QgsCoordinateReferenceSystem(a.project_crs))

    lname, lurl = BASEMAPS[a.basemap]
    base = QgsRasterLayer('type=xyz&zmin=0&zmax=19&url=' + lurl, lname, 'wms')

    l_pts = QgsVectorLayer(gpkg + '|layername=照片点位', '照片点位（编号）', 'ogr')
    l_trk = QgsVectorLayer(gpkg + '|layername=踏勘轨迹', '踏勘轨迹', 'ogr')
    l_area = QgsVectorLayer(gpkg + '|layername=' + a.area_name, a.area_name, 'ogr')
    for lyr in (l_pts, l_trk, l_area):
        if not lyr.isValid():
            raise SystemExit('图层打不开：' + lyr.source())

    l_pts.setRenderer(QgsSingleSymbolRenderer(QgsMarkerSymbol.createSimple({
        'name': 'circle', 'color': '0,150,200,255', 'size': '1.6',
        'outline_color': '255,255,255,255', 'outline_width': '0.3'})))
    pal = QgsPalLayerSettings()
    pal.fieldName = '编号'
    pal.isExpression = False
    try:                              # 3.30+ 作用域枚举；老版本用未作用域成员
        pal.placement = QgsPalLayerSettings.LabelPlacement.OverPoint
    except Exception:
        try:
            pal.placement = QgsPalLayerSettings.OverPoint
        except Exception:
            pass
    fmt = QgsTextFormat()
    fmt.setFont(load_font(a.label_size))
    fmt.setSize(a.label_size)
    fmt.setColor(QColor(0, 70, 140))
    buf = QgsTextBufferSettings()
    buf.setEnabled(True)
    buf.setSize(1.0)
    buf.setColor(QColor(255, 255, 255))
    fmt.setBuffer(buf)
    pal.setFormat(fmt)
    # 工作底图的用途是"每个编号都看得见"：允许重叠，不自动丢标
    try:
        pal.displayAll = True
        pal.obstacle = False
    except Exception:
        pass
    l_pts.setLabeling(QgsVectorLayerSimpleLabeling(pal))
    l_pts.setLabelsEnabled(True)

    l_trk.setRenderer(QgsSingleSymbolRenderer(QgsLineSymbol.createSimple({
        'color': '230,30,40,255', 'width': '0.9', 'capstyle': 'round', 'joinstyle': 'round'})))
    l_area.setRenderer(QgsSingleSymbolRenderer(QgsFillSymbol.createSimple({
        'color': '255,170,0,40', 'outline_color': '255,140,0,255',
        'outline_width': '0.8', 'outline_style': 'dash'})))

    for lyr in (l_pts, l_trk, l_area):
        proj.addMapLayer(lyr)
    if base.isValid():
        proj.addMapLayer(base)
    else:
        print('WARN 底图图层无效（离线也能用，只是没影像）')

    r = l_trk.extent()
    pad = 0.08
    r = QgsRectangle(r.xMinimum() - r.width() * pad, r.yMinimum() - r.height() * pad,
                     r.xMaximum() + r.width() * pad, r.yMaximum() + r.height() * pad)
    dest = QgsCoordinateReferenceSystem(a.project_crs)
    xf = QgsCoordinateTransform(l_trk.crs(), dest, proj)
    try:
        proj.viewSettings().setDefaultViewExtent(QgsReferencedRectangle(
            xf.transformBoundingBox(r), dest))
    except Exception as e:
        print('view extent skip:', e)
    # 相对路径保存：qgz 与 gpkg 同目录，整包拷走也不断链接
    try:
        proj.setFilePathStorage(QgsProject.FilePathType.Relative)
    except Exception:
        try:
            proj.setFilePathStorage(QgsProject.Relative)
        except Exception:
            pass
    proj.write(qgz)
    print('project ->', qgz)

    # --- KML
    def kml_esc(s):
        return str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

    style_pt = ('<Style id="pt"><IconStyle><color>ffd66914</color><scale>0.9</scale><Icon>'
                '<href>http://maps.google.com/mapfiles/kml/shapes/placemark_circle.png'
                '</href></Icon></IconStyle></Style>')

    def placemark(m, with_ext=True):
        seq = m['seq']
        d = desc.get(seq, '')
        if with_ext:
            return ('<Placemark><name>%d</name><styleUrl>#pt</styleUrl>'
                    '<description><![CDATA[<b>%s</b><br/>%s<br/>%s]]></description>'
                    '<ExtendedData><Data name="编号"><value>%d</value></Data>'
                    '<Data name="文件名"><value>%s</value></Data>'
                    '<Data name="拍摄时间"><value>%s</value></Data>'
                    '<Data name="画面内容"><value>%s</value></Data></ExtendedData>'
                    '<Point><coordinates>%.6f,%.6f,0</coordinates></Point></Placemark>' % (
                        seq, m['file'], m.get('time', ''), kml_esc(d), seq, m['file'],
                        m.get('time', ''), kml_esc(d), float(m['lon']), float(m['lat'])))
        return ('<Placemark><name>%d</name><styleUrl>#pt</styleUrl><description><![CDATA[%s]]>'
                '</description><Point><coordinates>%.6f,%.6f,0</coordinates></Point>'
                '</Placemark>' % (seq, kml_esc(d), float(m['lon']), float(m['lat'])))

    head = ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<kml xmlns="http://www.opengis.net/kml/2.2"><Document><name>%s</name>' % a.title)
    pts_kml = [head, '<description>照片点位 %d 个，编号与调研报告影像台账一致</description>' % len(meta),
               style_pt]
    pts_kml += [placemark(m) for m in meta]
    pts_kml.append('</Document></kml>')
    open(os.path.join(out, a.title + '_照片点位_编号.kml'), 'w', encoding='utf-8').write(
        '\n'.join(pts_kml))

    coords = '\n'.join('%.8f,%.8f,0' % (lo, la) for la, lo in track_pts)
    all_kml = [head,
               '<Style id="trk"><LineStyle><color>ff2823e6</color><width>4</width>'
               '</LineStyle></Style>', style_pt,
               '<Folder><name>踏勘轨迹</name><Placemark><name>踏勘轨迹</name><styleUrl>#trk</styleUrl>'
               '<LineString><tessellate>1</tessellate><altitudeMode>clampToGround</altitudeMode>'
               '<coordinates>%s</coordinates></LineString></Placemark></Folder>' % coords,
               '<Folder><name>照片点位</name>']
    all_kml += [placemark(m, with_ext=False) for m in meta]
    all_kml.append('</Folder></Document></kml>')
    open(os.path.join(out, a.title + '_轨迹与点位_合并.kml'), 'w', encoding='utf-8').write(
        '\n'.join(all_kml))
    print('kml done')

    # 给非 GIS 同事的入口说明
    write_open_note(out, a.title, len(meta), a.area_name)

    # --- 自检图（带编号；字体装上后能看清数字）
    if not a.skip_render:
        ms = QgsMapSettings()
        ms.setDestinationCrs(dest)
        ms.setOutputSize(QSize(2400, 1500))
        ms.setExtent(xf.transformBoundingBox(r))
        ms.setBackgroundColor(QColor(240, 240, 240))
        ms.setLayers([l_pts, l_trk, base] if base.isValid() else [l_pts, l_trk])
        job = QgsMapRendererParallelJob(ms)
        job.start()
        job.waitForFinished()
        img = job.renderedImage()
        png = os.path.join(out, '自检_点位分布.png')
        img.save(png)
        print('qc ->', png)

    print('EPSG 提示：CGCS2000 / 3-degree Gauss-Kruger zone 37 = EPSG:4525；'
          '若场址经度不在 109.5—112.5°E 之间，换对应带号，别硬用 4525。')


if __name__ == '__main__':
    main()
