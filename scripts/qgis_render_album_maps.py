#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""渲染现场图册的三级底图：总图 / 分区图 / 详图。

本脚本用 QGIS 无头运行器执行：
    D:\\QGIS_PROJ\\_tooling\\run_pyqgis.cmd qgis_render_album_maps.py \
        --gpx track.gpx --meta meta.json --footprints footprints.json \
        --out-dir album_maps

输出：
    detail.png + detail.json          详图底图（照片编号由合版脚本叠加）
    zone.png + zone.json              分区图底图
    total_tall.png + total_tall.json  总图纵向底图（合版时旋转 90° 横放）

坐标假设：GPX/meta/footprints 为 WGS84；输出为 EPSG:3857。
"""
import argparse, json, os
from qgis.core import (
    QgsVectorLayer, QgsRasterLayer, QgsProject, QgsMapSettings,
    QgsMapRendererParallelJob, QgsRectangle, QgsCoordinateReferenceSystem,
    QgsCoordinateTransform, QgsPointXY, QgsLineSymbol,
    QgsSingleSymbolRenderer, QgsMarkerSymbol, QgsGeometry, QgsFeature,
)
from qgis.PyQt.QtCore import QSize
from qgis.PyQt.QtGui import QColor
import xml.etree.ElementTree as ET

GOOGLE_URL = "https://mt1.google.com/vt/lyrs%3Ds%26x={x}%26y={y}%26z={z}"


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_track_points(gpx_path):
    root = ET.parse(gpx_path).getroot()
    return [
        (float(p.get("lat")), float(p.get("lon")))
        for p in root.iter("{http://www.topografix.com/GPX/1/1}trkpt")
    ]


def load_photo_points(footprints_path):
    raw = load_json(footprints_path)
    # 六只脚 footprintsjson: [time, lat, lon, ...]
    return [{"lat": float(f[1]), "lon": float(f[2])} for f in raw]


def line_layer(points, width, color):
    layer = QgsVectorLayer("LineString?crs=EPSG:4326", "track", "memory")
    feat = QgsFeature()
    feat.setGeometry(QgsGeometry.fromPolylineXY([QgsPointXY(lo, la) for la, lo in points]))
    layer.dataProvider().addFeature(feat)
    layer.updateExtents()
    layer.setRenderer(QgsSingleSymbolRenderer(QgsLineSymbol.createSimple({
        "color": color, "width": str(width), "capstyle": "round", "joinstyle": "round",
    })))
    return layer


def point_layer(items, size):
    layer = QgsVectorLayer("Point?crs=EPSG:4326", "photo_points", "memory")
    for m in items:
        feat = QgsFeature()
        feat.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(m["lon"], m["lat"])))
        layer.dataProvider().addFeature(feat)
    layer.updateExtents()
    layer.setRenderer(QgsSingleSymbolRenderer(QgsMarkerSymbol.createSimple({
        "name": "circle", "color": "20,90,220,255", "size": str(size),
        "outline_color": "255,255,255,255", "outline_width": "1.3",
    })))
    return layer


def render(cx, cy, extent_w, image_w, image_h, out_path, track_points, all_pts,
           base_url=GOOGLE_URL, line_w=4.2, case_w=7.6, point_size=3.4):
    # 宽高比与输出像素一致，保证比例尺不被拉伸
    extent_h = extent_w * image_h / image_w
    ext = QgsRectangle(cx - extent_w / 2, cy - extent_h / 2,
                       cx + extent_w / 2, cy + extent_h / 2)
    dest_crs = QgsCoordinateReferenceSystem("EPSG:3857")
    casing = line_layer(track_points, case_w, "255,255,255,235")
    track = line_layer(track_points, line_w, "235,35,45,255")
    points = point_layer(all_pts, point_size)
    base = QgsRasterLayer("type=xyz&zmin=1&zmax=20&url=" + base_url, "base", "wms")
    ms = QgsMapSettings()
    ms.setDestinationCrs(dest_crs)
    ms.setOutputSize(QSize(image_w, image_h))
    ms.setExtent(ext)
    ms.setBackgroundColor(QColor(240, 240, 240))
    ms.setLayers([points, track, casing, base])
    job = QgsMapRendererParallelJob(ms)
    job.start()
    job.waitForFinished()
    img = job.renderedImage()
    if img.isNull():
        raise RuntimeError("QGIS 渲染失败：%s" % out_path)
    img.save(out_path)
    with open(os.path.splitext(out_path)[0] + ".json", "w", encoding="utf-8") as f:
        json.dump({
            "xmin": ext.xMinimum(), "xmax": ext.xMaximum(),
            "ymin": ext.yMinimum(), "ymax": ext.yMaximum(),
            "img_w": image_w, "img_h": image_h,
            "extent_width_m": ext.width(), "extent_height_m": ext.height(),
        }, f, ensure_ascii=False, indent=2)
    print("saved:", out_path, image_w, image_h, "extent %.1fx%.1f m" % (ext.width(), ext.height()))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gpx", required=True)
    ap.add_argument("--meta", required=True, help="选入详图的照片 JSON（含 lat/lon/file）")
    ap.add_argument("--footprints", required=True, help="全部脚印 JSON")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--detail-width-m", type=float, default=180.0)
    ap.add_argument("--zone-width-m", type=float, default=360.0)
    ap.add_argument("--total-width-m", type=float, default=1100.0)
    ap.add_argument("--detail-size", default="2680x1440")
    ap.add_argument("--zone-size", default="2120x930")
    ap.add_argument("--total-size", default=None,
                    help="总图像素；缺省按 --total-orient 决定（tall=1000x4545，wide=4545x1000）")
    ap.add_argument("--total-orient", choices=["tall", "wide", "auto"], default="tall",
                    help="tall=纵向旋转（旧默认）；wide=横向总图；auto=按轨迹长轴自动选")
    ap.add_argument("--total-pad", type=float, default=1.25, help="auto/wide 时总图四周余量系数")
    ap.add_argument("--base-url", default=GOOGLE_URL)
    a = ap.parse_args()

    track_pts = load_track_points(a.gpx)
    meta_pts = load_json(a.meta)
    all_pts = load_photo_points(a.footprints)
    os.makedirs(a.out_dir, exist_ok=True)

    def size(s):
        w, h = s.lower().split("x")
        return int(w), int(h)

    dw, dh = size(a.detail_size)
    zw, zh = size(a.zone_size)

    # 详图/分区图中心：照片簇中心
    clat = sum(float(m["lat"]) for m in meta_pts) / len(meta_pts)
    clon = sum(float(m["lon"]) for m in meta_pts) / len(meta_pts)
    src = QgsCoordinateReferenceSystem("EPSG:4326")
    dst = QgsCoordinateReferenceSystem("EPSG:3857")
    xf = QgsCoordinateTransform(src, dst, QgsProject.instance())
    center = xf.transform(QgsPointXY(clon, clat))

    # 总图中心 / 范围：整条轨迹包围盒
    lats = [p[0] for p in track_pts]
    lons = [p[1] for p in track_pts]
    tbb = xf.transformBoundingBox(QgsRectangle(min(lons), min(lats), max(lons), max(lats)))
    tcenter = tbb.center()

    orient = a.total_orient
    if orient == "auto":
        orient = "wide" if tbb.width() >= tbb.height() else "tall"
    total_w = a.total_width_m
    if orient == "wide":
        tw, th = size(a.total_size) if a.total_size else (4545, 1000)
        aspect = tw / float(th)
        # 横向总图：东西向要盖住轨迹长轴
        total_w = max(tbb.width(), tbb.height() * aspect) * a.total_pad
    else:
        tw, th = size(a.total_size) if a.total_size else (1000, 4545)

    render(center.x(), center.y(), a.detail_width_m, dw, dh,
           os.path.join(a.out_dir, "detail.png"), track_pts, meta_pts,
           base_url=a.base_url, line_w=4.4, case_w=8.0, point_size=3.8)
    render(center.x(), center.y(), a.zone_width_m, zw, zh,
           os.path.join(a.out_dir, "zone.png"), track_pts, all_pts,
           base_url=a.base_url, line_w=3.6, case_w=6.6, point_size=2.7)
    render(tcenter.x(), tcenter.y(), total_w, tw, th,
           os.path.join(a.out_dir, "total_tall.png"), track_pts, all_pts,
           base_url=a.base_url, line_w=6.2, case_w=11.0, point_size=2.2)
    print("total orient=%s size=%dx%d width=%.0f m" % (orient, tw, th, total_w))


if __name__ == "__main__":
    main()
