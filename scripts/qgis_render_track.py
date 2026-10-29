#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""轨迹 QGIS 无头出图（field-survey-report skill）

必须在 QGIS 环境下运行（本机封装好的运行器）：
    D:\QGIS_PROJ\_tooling\run_pyqgis.cmd qgis_render_track.py \
        --track <原始轨迹.json> --out <map.png> --title "佛山市南海区「中北」现场踏勘轨迹" \
        --subtitle "六只脚 #4566590   徒步 1.34 km   用时 1:05   2021-07-26"

说明：
- 底图默认天地图影像（--basemap tdt），可换 --basemap esri。
- 输出范围按 --size 的宽高比对齐（默认 2400x1600 = 3:2），否则比例尺会不准。
- 同时写一份 sidecar JSON（<out>.json），给 decorate_map.py 算比例尺用。
"""
import argparse, json, os

from qgis.core import (QgsVectorLayer, QgsRasterLayer, QgsProject, QgsMapSettings,
                       QgsMapRendererParallelJob, QgsRectangle, QgsCoordinateReferenceSystem,
                       QgsCoordinateTransform, QgsPointXY, QgsLineSymbol,
                       QgsSingleSymbolRenderer, QgsMarkerSymbol, QgsGeometry, QgsFeature)
from qgis.PyQt.QtCore import QSize
from qgis.PyQt.QtGui import QColor

TDT_TK = "07257d307fac83023670da2011345cec"

def _line(pts, name, color, width):
    lyr = QgsVectorLayer("LineString?crs=EPSG:4326", name, "memory")
    f = QgsFeature()
    f.setGeometry(QgsGeometry.fromPolylineXY([QgsPointXY(p[2], p[1]) for p in pts]))
    lyr.dataProvider().addFeature(f)
    lyr.updateExtents()
    lyr.setRenderer(QgsSingleSymbolRenderer(QgsLineSymbol.createSimple(
        {"color": color, "width": width, "capstyle": "round", "joinstyle": "round"})))
    return lyr

def _point(pt, name, color):
    lyr = QgsVectorLayer("Point?crs=EPSG:4326", name, "memory")
    f = QgsFeature()
    f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(pt[2], pt[1])))
    lyr.dataProvider().addFeature(f)
    lyr.updateExtents()
    lyr.setRenderer(QgsSingleSymbolRenderer(QgsMarkerSymbol.createSimple(
        {"name": "circle", "color": color, "size": "6.5",
         "outline_color": "255,255,255,255", "outline_width": "1.8"})))
    return lyr

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--track", required=True, help="六只脚 trackjson")
    ap.add_argument("--out", required=True)
    ap.add_argument("--title", default="")
    ap.add_argument("--subtitle", default="")
    ap.add_argument("--size", default="2400x1600")
    ap.add_argument("--margin", type=float, default=0.15, help="四周留白比例")
    ap.add_argument("--basemap", default="tdt", choices=["tdt", "esri", "custom"])
    ap.add_argument("--base-url", default="", help="自定义 XYZ 底图模板（--basemap custom 时必填）")
    ap.add_argument("--ann-url", default="", help="可选注记瓦片模板（天地图 cia_w 之类）")
    ap.add_argument("--line-color", default="235,35,45,255")
    a = ap.parse_args()

    W, H = (int(x) for x in a.size.lower().split("x"))
    aspect = W / H

    raw = json.load(open(a.track, encoding="utf-8"))
    segs = raw if isinstance(raw[0][0], list) else [raw]
    pts = [p for s in segs for p in s]

    casing = _line(pts, "casing", "255,255,255,240", "7.5")
    main = _line(pts, "main", a.line_color, "3.6")
    sp = _point(pts[0], "start", "25,180,95,255")
    ep = _point(pts[-1], "end", "240,60,40,255")

    if a.basemap == "tdt":
        iu = ("https://t0.tianditu.gov.cn/DataServer?T=img_w%26x={x}%26y={y}%26l={z}%26tk=" + TDT_TK)
        au = ("https://t0.tianditu.gov.cn/DataServer?T=cia_w%26x={x}%26y={y}%26l={z}%26tk=" + TDT_TK)
    elif a.basemap == "custom":
        if not a.base_url:
            raise SystemExit("--basemap custom 需要同时给 --base-url")
        iu, au = a.base_url, a.ann_url
    else:
        iu = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
        au = ""
    base = QgsRasterLayer("type=xyz&zmin=1&zmax=18&url=" + iu, "base", "wms")
    ann = QgsRasterLayer("type=xyz&zmin=1&zmax=18&url=" + au, "ann", "wms") if au else None

    crs = QgsCoordinateReferenceSystem("EPSG:4326")
    mcrs = QgsCoordinateReferenceSystem("EPSG:3857")
    xf = QgsCoordinateTransform(crs, mcrs, QgsProject.instance())
    bb = xf.transformBoundingBox(QgsRectangle(min(p[2] for p in pts), min(p[1] for p in pts),
                                              max(p[2] for p in pts), max(p[1] for p in pts)))
    w = bb.width() * (1 + 2 * a.margin)
    h = bb.height() * (1 + 2 * a.margin)
    cx, cy = bb.center().x(), bb.center().y()
    outw, outh = (w, w / aspect) if w / h > aspect else (h * aspect, h)
    ext = QgsRectangle(cx - outw / 2, cy - outh / 2, cx + outw / 2, cy + outh / 2)

    ms = QgsMapSettings()
    ms.setDestinationCrs(mcrs)
    ms.setOutputSize(QSize(W, H))
    ms.setExtent(ext)
    ms.setBackgroundColor(QColor(238, 238, 238))
    layers = [ep, sp, main, casing] + ([ann] if ann else []) + [base]
    ms.setLayers(layers)          # 列表首个在最上层
    job = QgsMapRendererParallelJob(ms)
    job.start()
    job.waitForFinished()
    ok = job.renderedImage().save(a.out)

    json.dump({"extent_width_m": ext.width(), "extent_height_m": ext.height(),
               "img_w": W, "img_h": H, "n": len(pts),
               "lat": [min(p[1] for p in pts), max(p[1] for p in pts)],
               "lon": [min(p[2] for p in pts), max(p[2] for p in pts)],
               "title": a.title, "subtitle": a.subtitle},
              open(os.path.splitext(a.out)[0] + ".json", "w", encoding="utf-8"))
    print("saved:", ok, a.out, "extent %.0fx%.0f m" % (ext.width(), ext.height()))

if __name__ == "__main__":
    main()
