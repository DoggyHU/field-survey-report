#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""地图装饰（field-survey-report skill）：标题卡 / 图例 / 比例尺 / 指北针 + 轻微提亮

用法:
    python decorate_map.py --in map.png --sidecar map.json --out 路线图.jpg \
        --title "佛山市南海区「中北」现场踏勘轨迹" \
        --subtitle "六只脚 #4566590   徒步 1.34 km   用时 1:05   2021-07-26" \
        --scale-m 50

比例尺长度可省略，脚本会按地图横向跨度自动挑一个"整数档"（50/100/200/500/1000/2000 米）。
字体需本机存在 msyh.ttc / msyhbd.ttc（Windows 自带）。
"""
import argparse, json, os
from PIL import Image, ImageDraw, ImageFont, ImageEnhance

REG = r"C:\Windows\Fonts\msyh.ttc"
BOLD = r"C:\Windows\Fonts\msyhbd.ttc"

def _f(size, bold=False):
    return ImageFont.truetype(BOLD if bold else REG, size)

def pick_scale(extent_w_m, img_w):
    for s in (50, 100, 200, 500, 1000, 2000, 5000):
        if 120 <= s / (extent_w_m / img_w) <= 420:
            return s
    return 200

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="src", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--sidecar", default="")
    ap.add_argument("--title", default="")
    ap.add_argument("--subtitle", default="")
    ap.add_argument("--scale-m", type=int, default=0)
    ap.add_argument("--legend-label", default="踏勘轨迹")
    ap.add_argument("--no-endpoints", action="store_true", help="图例中不显示起点/终点（详图、分区图用）")
    ap.add_argument("--source", default="底图：天地图影像    轨迹数据：六只脚")
    a = ap.parse_args()

    info = {}
    sc = a.sidecar or os.path.splitext(a.src)[0] + ".json"
    if os.path.exists(sc):
        info = json.load(open(sc, encoding="utf-8"))
    title = a.title or info.get("title", "")
    subtitle = a.subtitle or info.get("subtitle", "")

    im = Image.open(a.src).convert("RGB")
    im = ImageEnhance.Brightness(im).enhance(1.12)
    im = ImageEnhance.Color(im).enhance(1.06)
    im = ImageEnhance.Contrast(im).enhance(1.05)
    W, H = im.size
    dr = ImageDraw.Draw(im, "RGBA")

    if title:
        dr.rounded_rectangle([40, 40, 40 + 1120, 40 + 196], 16, (255, 255, 255, 234), (30, 30, 30, 40), 2)
        dr.rectangle([40, 40, 52, 236], fill=(235, 35, 45, 255))
        dr.text((80, 64), title, font=_f(48, True), fill=(18, 18, 18, 255))
        if subtitle:
            dr.text((82, 142), subtitle, font=_f(30), fill=(70, 70, 70, 255))

    cx, cy = W - 140, 120
    dr.ellipse([cx - 60, cy - 60, cx + 60, cy + 60], fill=(255, 255, 255, 226), outline=(30, 30, 30, 60), width=2)
    dr.polygon([(cx, cy - 42), (cx - 21, cy + 24), (cx, cy + 9), (cx + 21, cy + 24)], fill=(40, 40, 40, 255))
    dr.text((cx - 11, cy + 28), "N", font=_f(28, True), fill=(40, 40, 40, 255))

    lx, ly = 48, H - 206
    legend_h = 96 if a.no_endpoints else 156
    dr.rounded_rectangle([lx, ly, lx + 430, ly + legend_h], 14, (255, 255, 255, 230), (30, 30, 30, 40), 2)
    dr.line([lx + 30, ly + 48, lx + 110, ly + 48], fill=(255, 255, 255, 255), width=9)
    dr.line([lx + 30, ly + 48, lx + 110, ly + 48], fill=(235, 35, 45, 255), width=4)
    dr.text((lx + 134, ly + 32), a.legend_label, font=_f(30), fill=(25, 25, 25, 255))
    if not a.no_endpoints:
        dr.ellipse([lx + 58, ly + 86, lx + 82, ly + 110], fill=(25, 180, 95, 255), outline=(255, 255, 255, 255), width=3)
        dr.text((lx + 134, ly + 82), "起点", font=_f(30), fill=(25, 25, 25, 255))
        dr.ellipse([lx + 232, ly + 86, lx + 256, ly + 110], fill=(240, 60, 40, 255), outline=(255, 255, 255, 255), width=3)
        dr.text((lx + 288, ly + 82), "终点", font=_f(30), fill=(25, 25, 25, 255))

    if info.get("extent_width_m"):
        sm = a.scale_m or pick_scale(info["extent_width_m"], info.get("img_w", W))
        mpp = info["extent_width_m"] / info.get("img_w", W)
        px = sm / mpp
        sx, sy = int(W - 70 - px), H - 96
        dr.rectangle([sx - 18, sy - 42, sx + int(px) + 18, sy + 44], fill=(255, 255, 255, 224))
        dr.line([sx, sy, sx + px, sy], fill=(30, 30, 30, 255), width=8)
        for xx in (sx, sx + px):
            dr.line([xx, sy - 14, xx, sy + 14], fill=(30, 30, 30, 255), width=8)
        dr.text((sx - 6, sy + 14), "0", font=_f(24), fill=(30, 30, 30, 255))
        lab = "%dm" % sm if sm < 1000 else "%.1fkm" % (sm / 1000.0)
        dr.text((int(sx + px) - 24, sy + 14), lab, font=_f(24), fill=(30, 30, 30, 255))

    if a.source:
        dr.text((52, H - 38), a.source, font=_f(24), fill=(20, 20, 20, 210))
    dr.rectangle([0, 0, W - 1, H - 1], outline=(255, 255, 255, 255), width=6)
    im.save(a.out, quality=88) if a.out.lower().endswith((".jpg", ".jpeg")) else im.save(a.out)
    print("saved:", a.out, im.size)

if __name__ == "__main__":
    main()
