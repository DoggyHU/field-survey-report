#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把总图/分区图/详图底图与 12 张现场照片合成为 A3 横排图册页。

用法：
    python compose_album_a3.py \
        --map-dir album_maps \
        --meta meta.json \
        --photo-dir photos \
        --out 详图_A3_12张.jpg \
        --title "详图 1 ｜ 恩平市大田 沿线风貌 —— 村口段" \
        --subtitle "六只脚 #100131607 ｜ 详图 1:800 ｜ 底图：Google 卫星 ｜ 照片 1 ~ 12 ｜ 隶属 分区图 A"

规则：
- 详图内照片编号为 1、2、3…；照片下方为“1 p03.jpg”，不写 1-1。
- 分区图内红框 = 本幅详图范围；总图内红框 = 本幅分区图范围；不写“红框=本幅”说明。
- 详图和分区图不显示起点/终点图例。
- A3 横排 300 dpi，12 张照片 4×3 密排。
"""
import argparse, json, math, os, re
from PIL import Image, ImageDraw, ImageFont, ImageEnhance, ImageOps

R = 6378137.0


def merc(lat, lon):
    return R * math.radians(lon), R * math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def font(size, bold=False):
    return ImageFont.truetype(r"C:\Windows\Fonts\msyhbd.ttc" if bold else r"C:\Windows\Fonts\msyh.ttc", size)


def text_center(dr, xy, s, f, fill):
    b = dr.textbbox((0, 0), s, font=f)
    dr.text((xy[0] - (b[2] - b[0]) / 2, xy[1] - (b[3] - b[1]) / 2 - 2), s, font=f, fill=fill)


def _clip_rect(x0, y0, x1, y1, box):
    """把矩形裁剪到描边面板范围内，避免反索引框跨版面乱画"""
    bx, by, bw, bh = box
    x0 = max(bx, min(x0, bx + bw)); x1 = max(bx, min(x1, bx + bw))
    y0 = max(by, min(y0, by + bh)); y1 = max(by, min(y1, by + bh))
    return x0, y0, x1, y1


def pick_scale(extent_w_m, img_w):
    """按图面横向范围挑一个整数比例尺档，保证比例尺条长度适中

    2026-10-28：档位下探到 5/10/20/25 m。原来最小档 50 m，在 180 m 幅面（1:800）
    下 50 m 已是 744 px（远超 460 px 上限），函数落到兜底 200 m，比例尺条宽度
    2977 px、直接横贯整幅并压住图例。
    """
    for s in (5, 10, 20, 25, 50, 100, 200, 500, 1000, 2000):
        px = s / (extent_w_m / img_w)
        if 120 <= px <= 460:
            return s
    return 200


def paste_panel(page, dr, box, image_path, title, enhance=True):
    x, y, w, h = box
    im = Image.open(image_path).convert("RGB")
    if enhance:
        im = ImageEnhance.Brightness(im).enhance(1.10)
        im = ImageEnhance.Color(im).enhance(1.05)
    im = ImageOps.fit(im, (w, h), method=Image.LANCZOS, centering=(0.5, 0.5))
    page.paste(im, (x, y))
    dr.rectangle([x, y, x + w - 1, y + h - 1], outline=(45, 45, 45, 255), width=5)
    tb = dr.textbbox((0, 0), title, font=font(34, True))
    bw = max(260, (tb[2] - tb[0]) + 52)
    dr.rectangle([x + 6, y + 6, x + bw, y + 64], fill=(255, 255, 255, 242))
    dr.text((x + 20, y + 13), title, font=font(34, True), fill=(20, 20, 20, 255))


def draw_detail_labels(dr, box, detail, meta):
    mx, my, mw, mh = box
    mx0, mx1, my0, my1 = detail["xmin"], detail["xmax"], detail["ymin"], detail["ymax"]
    pts = []
    for m in meta:
        X, Y = merc(float(m["lat"]), float(m["lon"]))
        px = mx + (X - mx0) / (mx1 - mx0) * mw
        py = my + (my1 - Y) / (my1 - my0) * mh
        pts.append((px, py))

    placed, labels = [], []
    label_r = 28
    for k, (px, py) in enumerate(pts):
        chosen = None
        for rad in (46, 62, 82, 105, 132, 162, 198, 238):
            for ang in range(0, 360, 30):
                a = math.radians(ang)
                lx, ly = px + rad * math.cos(a), py + rad * math.sin(a)
                box2 = [lx - label_r - 8, ly - label_r - 8, lx + label_r + 8, ly + label_r + 8]
                if box2[0] < mx + 8 or box2[1] < my + 8 or box2[2] > mx + mw - 8 or box2[3] > my + mh - 8:
                    continue
                if any(not (box2[2] < b[0] or box2[0] > b[2] or box2[3] < b[1] or box2[1] > b[3]) for b in placed):
                    continue
                chosen = (lx, ly, box2)
                break
            if chosen:
                break
        if not chosen:
            lx, ly = px + 60, py - 60
            chosen = (lx, ly, [lx - label_r - 8, ly - label_r - 8, lx + label_r + 8, ly + label_r + 8])
        lx, ly, box2 = chosen
        placed.append(box2)
        labels.append((k + 1, px, py, lx, ly))

    for n, px, py, lx, ly in labels:
        dr.line([px, py, lx, ly], fill=(255, 255, 255, 235), width=7)
        dr.line([px, py, lx, ly], fill=(20, 90, 220, 255), width=3)
        dr.ellipse([px - 8, py - 8, px + 8, py + 8], fill=(20, 90, 220, 255), outline=(255, 255, 255, 255), width=3)
        dr.ellipse([lx - label_r, ly - label_r, lx + label_r, ly + label_r], fill=(20, 90, 220, 255), outline=(255, 255, 255, 255), width=4)
        text_center(dr, (lx, ly), str(n), font(30, True), (255, 255, 255, 255))
    return labels


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--map-dir", required=True)
    ap.add_argument("--meta", required=True)
    ap.add_argument("--photo-dir", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--pdf", default="")
    ap.add_argument("--title", default="详图 1 ｜ 现场踏勘照片索引")
    ap.add_argument("--subtitle", default="")
    ap.add_argument("--detail-title", default="详图（1:800）")
    ap.add_argument("--zone-title", default="分区图（反索引）")
    ap.add_argument("--total-title", default="总图（反索引）")
    ap.add_argument("--photos-per-page", type=int, default=12)
    ap.add_argument("--scale-m", type=int, default=50)
    ap.add_argument("--scale-auto", action="store_true", help="比例尺档位按图面范围自动选")
    a = ap.parse_args()

    if a.photos_per_page != 12:
        raise SystemExit("当前合版脚本固定 12 张（4×3）；后续分页功能再扩展。")

    V = a.map_dir
    detail = load_json(os.path.join(V, "detail.json"))
    zone = load_json(os.path.join(V, "zone.json"))
    total = load_json(os.path.join(V, "total_tall.json"))
    meta = load_json(a.meta)[:a.photos_per_page]
    if not meta:
        raise SystemExit("meta 为空，没有照片可排版。")

    PW, PH = 4961, 3508
    page = Image.new("RGB", (PW, PH), (255, 255, 255))
    dr = ImageDraw.Draw(page, "RGBA")

    # header
    dr.rectangle([0, 0, PW, 200], fill=(245, 246, 248, 255))
    dr.rectangle([0, 0, 18, 200], fill=(235, 35, 45, 255))
    dr.text((58, 26), a.title, font=font(62, True), fill=(20, 20, 20, 255))
    if a.subtitle:
        dr.text((60, 116), a.subtitle, font=font(33), fill=(80, 80, 80, 255))

    # top band
    P1 = (60, 220, 2680, 1440)       # detail
    P2 = (2780, 220, 2120, 930)      # zone
    P3 = (2780, 1190, 2120, 470)     # total strip

    paste_panel(page, dr, P1, os.path.join(V, "detail.png"), a.detail_title)
    paste_panel(page, dr, P2, os.path.join(V, "zone.png"), a.zone_title)

    x, y, w, h = P3
    tot = Image.open(os.path.join(V, "total_tall.png")).convert("RGB")
    rotated = tot.height > tot.width          # 纵向长条才旋转 90°；横向总图直接用
    if rotated:
        tot = tot.rotate(90, expand=True)
    rot = ImageOps.fit(tot, (w, h), method=Image.LANCZOS, centering=(0.5, 0.5))
    rot = ImageEnhance.Brightness(rot).enhance(1.10)
    rot = ImageEnhance.Color(rot).enhance(1.05)
    page.paste(rot, (x, y))
    dr.rectangle([x, y, x + w - 1, y + h - 1], outline=(45, 45, 45, 255), width=5)
    dr.rectangle([x + 6, y + 6, x + 340, y + 64], fill=(255, 255, 255, 242))
    dr.text((x + 20, y + 13), a.total_title, font=font(34, True), fill=(20, 20, 20, 255))

    # 反索引：分区图上的详图框
    zx, zy, zw, zh = P2
    zx0, zx1, zy0, zy1 = zone["xmin"], zone["xmax"], zone["ymin"], zone["ymax"]
    dx0, dx1, dy0, dy1 = detail["xmin"], detail["xmax"], detail["ymin"], detail["ymax"]
    rx0 = zx + (dx0 - zx0) / (zx1 - zx0) * zw
    rx1 = zx + (dx1 - zx0) / (zx1 - zx0) * zw
    ry0 = zy + (zy1 - dy1) / (zy1 - zy0) * zh
    ry1 = zy + (zy1 - dy0) / (zy1 - zy0) * zh
    rx0, ry0, rx1, ry1 = _clip_rect(rx0, ry0, rx1, ry1, P2)
    dr.rectangle([rx0, ry0, rx1, ry1], outline=(235, 35, 45, 255), width=7)

    # 反索引：总图上的分区图框（纵向源图旋转 90° 后显示；横向总图按原图坐标）
    tx, ty, tw, th = P3
    tx0, tx1, ty0, ty1 = total["xmin"], total["xmax"], total["ymin"], total["ymax"]
    corners = []
    for xx in (zx0, zx1):
        for yy in (zy0, zy1):
            u = (xx - tx0) / (tx1 - tx0)
            v = (ty1 - yy) / (ty1 - ty0)
            corners.append((v, 1 - u) if rotated else (u, v))
    xs = [c[0] for c in corners]
    ys = [c[1] for c in corners]
    gx0, gy0, gx1, gy1 = _clip_rect(tx + min(xs) * tw, ty + min(ys) * th,
                                    tx + max(xs) * tw, ty + max(ys) * th, P3)
    dr.rectangle([gx0, gy0, gx1, gy1], outline=(235, 35, 45, 255), width=7)

    # 详图照片编号 / 引线
    draw_detail_labels(dr, P1, detail, meta)

    # 详图图例（不含起点/终点）
    mx, my, mw, mh = P1
    lx, ly = mx + 28, my + mh - 164
    dr.rounded_rectangle([lx, ly, lx + 560, ly + 136], 14,
                         fill=(255, 255, 255, 238), outline=(110, 110, 110, 255), width=2)
    dr.line([lx + 28, ly + 42, lx + 128, ly + 42], fill=(255, 255, 255, 255), width=10)
    dr.line([lx + 28, ly + 42, lx + 128, ly + 42], fill=(235, 35, 45, 255), width=5)
    dr.text((lx + 148, ly + 22), "踏勘轨迹", font=font(30), fill=(25, 25, 25, 255))
    dr.ellipse([lx + 60, ly + 84, lx + 92, ly + 116], fill=(20, 90, 220, 255), outline=(255, 255, 255, 255), width=3)
    dr.text((lx + 148, ly + 82), "照片拍摄点（编号）", font=font(30), fill=(25, 25, 25, 255))

    # 比例尺
    mpp = detail["extent_width_m"] / mw
    sm = pick_scale(detail["extent_width_m"], mw) if a.scale_auto else a.scale_m
    px = sm / mpp
    sx, sy = mx + mw - 60 - px, my + mh - 78
    dr.rectangle([sx - 18, sy - 42, sx + px + 18, sy + 44], fill=(255, 255, 255, 236))
    dr.line([sx, sy, sx + px, sy], fill=(30, 30, 30, 255), width=9)
    for xx in (sx, sx + px):
        dr.line([xx, sy - 14, xx, sy + 14], fill=(30, 30, 30, 255), width=9)
    dr.text((sx - 6, sy + 16), "0", font=font(26), fill=(30, 30, 30, 255))
    dr.text((sx + px - 42, sy + 16), f"{sm}m", font=font(26), fill=(30, 30, 30, 255))

    # 照片 4×3
    PX0, PY0 = 60, 1745
    PWt, PHt = 4841, 1680
    cols, rows = 4, 3
    cw, ch = PWt // cols, PHt // rows
    for k, m in enumerate(meta):
        r, c = divmod(k, cols)
        cx0, cy0 = PX0 + c * cw, PY0 + r * ch
        im = Image.open(os.path.join(a.photo_dir, m["file"])).convert("RGB")
        im = ImageOps.fit(im, (cw - 42, ch - 106), method=Image.LANCZOS, centering=(0.5, 0.5))
        ox = cx0 + (cw - im.width) // 2
        oy = cy0 + 10
        page.paste(im, (ox, oy))
        dr.rectangle([ox, oy, ox + im.width - 1, oy + im.height - 1], outline=(40, 40, 40, 255), width=5)
        dr.rounded_rectangle([ox + 8, oy + 8, ox + 74, oy + 74], 10, fill=(20, 90, 220, 255))
        text_center(dr, (ox + 41, oy + 38), str(k + 1), font(34, True), (255, 255, 255, 255))
        cap_name = str(m.get("orig_file") or re.sub(r"^\d+_", "", str(m["file"]))).lower()
        cap = f"{k + 1} {cap_name}"
        bb = dr.textbbox((0, 0), cap, font=font(31))
        dr.text((ox + (im.width - (bb[2] - bb[0])) // 2, oy + im.height + 14), cap, font=font(31), fill=(45, 45, 45, 255))

    dr.rectangle([0, 0, PW - 1, PH - 1], outline=(130, 130, 130, 255), width=5)
    page.save(a.out, quality=92)
    print("saved:", a.out, page.size)
    if a.pdf:
        page.save(a.pdf, "PDF", resolution=300.0)
        print("saved:", a.pdf)


if __name__ == "__main__":
    main()
