#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一键生成 A3 横排现场图册，并只保留最终合体 PDF。

流程：
1) 按 --photos-per-page 自动分页（尾页不足 --min-last 张时与上一页均衡）；
2) 每页调用 QGIS 渲染总图 / 分区图 / 详图底图；
3) 每页调用 compose_album_a3.py 合成 A3 横排页；
4) 将各页 PDF 合并为最终 PDF；
5) 默认删除分页临时目录、单页 JPG、单页 PDF和分幅底图。

用法：
    python build_album.py \
        --gpx track.gpx --meta meta_archived.json --footprints footprints.json \
        --photo-dir 照片归档 --out-dir out \
        --title "大田沿线风貌｜现场图册" \
        --subtitle "六只脚 #100131607｜底图：Google 卫星" \
        --final-pdf "大田沿线风貌_现场图册_A3.pdf"

自适应（默认关闭，保持旧行为）：
    --detail-auto          按每页照片包围盒自动定详图范围（180~900 m）
    --total-orient auto    按轨迹长轴自动选总图方向（横排/竖排）
    --scale-auto           按图面范围自动选比例尺档位

仅保留最终 PDF；如需调试分页，加 --keep-pages。
"""
import argparse, json, math, os, shutil, subprocess, sys
from pathlib import Path

DEFAULT_QGIS = r"D:\QGIS_PROJ\_tooling\run_pyqgis.cmd"
DEFAULT_BASE = "https://mt1.google.com/vt/lyrs%3Ds%26x={x}%26y={y}%26z={z}"
DETAIL_ASPECT = 2680.0 / 1440.0     # 详图画幅宽高比
MM_PER_PX_300DPI = 118.11           # 300 dpi → 每厘米像素


def load_config(path):
    if not path:
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def pick(ns, cfg, key, default=None):
    val = getattr(ns, key, None)
    if val is not None:
        return val
    return cfg.get(key, default)


def haversine_m(a, b):
    lat1, lon1 = math.radians(float(a["lat"])), math.radians(float(a["lon"]))
    lat2, lon2 = math.radians(float(b["lat"])), math.radians(float(b["lon"]))
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 6371000.0 * 2 * math.asin(math.sqrt(h))


def merc(lat, lon):
    R = 6378137.0
    return R * math.radians(lon), R * math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))


def bbox_span(items):
    """页内照片包围盒（米）"""
    XY = [merc(float(m["lat"]), float(m["lon"])) for m in items]
    xs = [p[0] for p in XY]
    ys = [p[1] for p in XY]
    return max(xs) - min(xs), max(ys) - min(ys)


def paginate(items, n, gap_m):
    pages, current = [], []
    for item in items:
        if current:
            too_many = len(current) >= n
            too_far = gap_m and gap_m > 0 and haversine_m(current[-1], item) > gap_m
            if too_many or too_far:
                pages.append(current)
                current = []
        current.append(item)
    if current:
        pages.append(current)
    return pages


def balance_tail(pages, min_last=4):
    """尾页太薄（如只剩 1 张）时，从上一页挪几张过来，避免孤立页"""
    while len(pages) > 1 and 0 < len(pages[-1]) < min_last and len(pages[-2]) > min_last:
        pages[-1].insert(0, pages[-2].pop())
    return pages


def merge_pdfs(page_pdfs, final_pdf):
    import fitz
    out = fitz.open()
    try:
        for p in page_pdfs:
            src = fitz.open(p)
            out.insert_pdf(src)
            src.close()
        final_pdf.parent.mkdir(parents=True, exist_ok=True)
        out.save(final_pdf)
    finally:
        out.close()


def make_work_dir(base, prefix="_album_tmp_"):
    """替代 tempfile.mkdtemp：个别机器/沙箱下 mkdtemp 建出的目录无法再写入（WinError 5）"""
    base = Path(base)
    base.mkdir(parents=True, exist_ok=True)
    for i in range(10000):
        p = base / ("%s%d" % (prefix, i))
        try:
            p.mkdir(parents=True)
            return p
        except FileExistsError:
            continue
    raise RuntimeError("无法创建图册工作目录：%s" % base)


def nice_scale(detail_w):
    """按 300 dpi、2680 px 图幅把范围宽度换算成比例尺分母，并取整到 50/100"""
    raw = detail_w * 100.0 * MM_PER_PX_300DPI / 2680.0
    step = 50 if raw < 2000 else 100
    return int(round(raw / step) * step)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", help="JSON 配置文件；命令行参数优先")
    ap.add_argument("--gpx")
    ap.add_argument("--meta", help="全部照片 meta JSON，含 file/lat/lon，可选 orig_file")
    ap.add_argument("--footprints", help="全部脚印 JSON")
    ap.add_argument("--photo-dir", help="照片目录；建议传归档目录")
    ap.add_argument("--out-dir")
    ap.add_argument("--final-pdf", help="最终合体 PDF 路径；默认 out-dir/现场图册_A3.pdf")
    ap.add_argument("--work-dir", default=None, help="工作目录；默认在 out-dir 下自动建")
    ap.add_argument("--photos-per-page", type=int, default=None)
    ap.add_argument("--min-last", type=int, default=None, help="尾页最少张数，不足与上一页均衡")
    ap.add_argument("--page-gap-m", type=float, default=None, help="相邻照片间距超过该值时自动另起一页")
    ap.add_argument("--keep-pages", action="store_true", help="保留分页临时文件和单页成果，用于调试")
    ap.add_argument("--title", default=None)
    ap.add_argument("--subtitle", default=None)
    ap.add_argument("--detail-title", default=None)
    ap.add_argument("--zone-title", default=None)
    ap.add_argument("--total-title", default=None)
    ap.add_argument("--detail-width-m", type=float, default=None)
    ap.add_argument("--zone-width-m", type=float, default=None)
    ap.add_argument("--total-width-m", type=float, default=None)
    ap.add_argument("--detail-auto", action="store_true", default=None,
                    help="按每页照片包围盒自动定详图范围（推荐；与 --detail-width-m 互斥）")
    ap.add_argument("--detail-margin", type=float, default=None, help="自动范围的四周余量系数")
    ap.add_argument("--detail-min-m", type=float, default=None)
    ap.add_argument("--detail-max-m", type=float, default=None)
    ap.add_argument("--zone-factor", type=float, default=None, help="自动模式下分区图 = 详图 × 该系数")
    ap.add_argument("--map-levels", type=int, choices=[2, 3], default=None,
                    help="图册每页几级图：2=详图+总图（总图横排不旋转，默认）；3=详图+分区图+总图")
    ap.add_argument("--total-orient", choices=["tall", "wide", "auto"], default=None,
                    help="总图方向：tall=纵向旋转（旧默认），wide=横向，auto=按轨迹长轴自动")
    ap.add_argument("--total-size", default=None, help="总图输出像素，如 1000x4545 / 4545x1000")
    ap.add_argument("--scale-auto", action="store_true", default=None, help="比例尺档位按图面范围自动选")
    ap.add_argument("--qgis-runner", default=None)
    ap.add_argument("--base-url", default=None)
    a = ap.parse_args()
    cfg = load_config(a.config)
    here = Path(__file__).resolve().parent

    gpx = pick(a, cfg, "gpx")
    meta = pick(a, cfg, "meta")
    footprints = pick(a, cfg, "footprints")
    photo_dir = pick(a, cfg, "photo_dir")
    out_dir = pick(a, cfg, "out_dir")
    missing = [k for k, v in {
        "gpx": gpx, "meta": meta, "footprints": footprints,
        "photo_dir": photo_dir, "out_dir": out_dir,
    }.items() if not v]
    if missing:
        ap.error("缺少参数：" + ", ".join(missing))

    title = pick(a, cfg, "title", "现场图册")
    subtitle = pick(a, cfg, "subtitle", "")
    detail_width_m = pick(a, cfg, "detail_width_m", 180.0)
    zone_width_m = pick(a, cfg, "zone_width_m", 360.0)
    total_width_m = pick(a, cfg, "total_width_m", 1100.0)
    detail_auto = bool(pick(a, cfg, "detail_auto", False))
    scale_auto = bool(pick(a, cfg, "scale_auto", False))
    total_orient = pick(a, cfg, "total_orient", "tall")
    map_levels = int(pick(a, cfg, "map_levels", 2))
    total_size = pick(a, cfg, "total_size", None)
    qgis_runner = pick(a, cfg, "qgis_runner", os.environ.get("QGIS_RUNNER", DEFAULT_QGIS))
    base_url = pick(a, cfg, "base_url", DEFAULT_BASE)
    photos_per_page = int(pick(a, cfg, "photos_per_page", 12))
    page_gap_m = float(pick(a, cfg, "page_gap_m", 500.0))
    detail_margin = float(pick(a, cfg, "detail_margin", 1.35))
    detail_min_m = float(pick(a, cfg, "detail_min_m", 180.0))
    detail_max_m = float(pick(a, cfg, "detail_max_m", 900.0))
    zone_factor = float(pick(a, cfg, "zone_factor", 2.0))
    if photos_per_page <= 0:
        raise SystemExit("--photos-per-page 必须大于 0")

    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    meta_path = Path(meta).resolve()
    meta_items = json.loads(meta_path.read_text(encoding="utf-8"))
    if not isinstance(meta_items, list) or not meta_items:
        raise SystemExit("meta 必须是非空 JSON 数组")
    pages = balance_tail(paginate(meta_items, photos_per_page, page_gap_m),
                         int(pick(a, cfg, "min_last", 4)))
    final_pdf = Path(pick(a, cfg, "final_pdf", out_dir / "现场图册_A3.pdf")).resolve()
    if final_pdf.exists() and final_pdf.is_dir():
        raise SystemExit("--final-pdf 指向的是目录：%s" % final_pdf)

    work_dir = pick(a, cfg, "work_dir", None)
    if work_dir:
        work_root = Path(work_dir).resolve()
        work_root.mkdir(parents=True, exist_ok=True)
        cleanup = False
    else:
        work_root = make_work_dir(out_dir)
        cleanup = not (a.keep_pages or bool(cfg.get("keep_pages")))

    page_pdfs = []
    try:
        render_script = here / "qgis_render_album_maps.py"
        compose_script = here / "compose_album_a3.py"
        for idx, page_items in enumerate(pages, 1):
            page_dir = work_root / ("page_%02d" % idx)
            page_dir.mkdir(parents=True, exist_ok=True)
            page_meta = work_root / ("meta_%02d.json" % idx)
            page_meta.write_text(json.dumps(page_items, ensure_ascii=False, indent=2), encoding="utf-8")
            map_dir = page_dir / "_maps"

            if detail_auto:
                dx, dy = bbox_span(page_items)
                dw = max(dx, dy * DETAIL_ASPECT) * detail_margin
                dw = max(detail_min_m, min(detail_max_m, round(dw / 10.0) * 10))
                zw = round(dw * zone_factor / 10.0) * 10
            else:
                dw, zw = detail_width_m, zone_width_m

            cmd = [
                qgis_runner, str(render_script),
                "--gpx", str(gpx),
                "--meta", str(page_meta),
                "--footprints", str(footprints),
                "--out-dir", str(map_dir),
                "--detail-width-m", str(dw),
                "--zone-width-m", str(zw),
                "--total-width-m", str(total_width_m),
                "--total-orient", str(total_orient),
            ]
            if map_levels == 2:
                # 两级：只要详图+总图；总图按右列尺寸（2120x1440）横排渲染，不做旋转
                cmd += ["--maps", "detail,total",
                        "--total-size", "2120x1440",
                        "--total-orient", "wide"]
            elif total_size:
                cmd += ["--total-size", str(total_size)]
            if base_url and base_url != DEFAULT_BASE:
                cmd += ["--base-url", base_url]
            print("[%d/%d] QGIS render (detail %s m)" % (idx, len(pages), int(dw)))
            subprocess.run(cmd, check=True)

            start = sum(len(x) for x in pages[:idx - 1]) + 1
            end = start + len(page_items) - 1
            page_title = title if len(pages) == 1 else "%s｜第 %d/%d 页" % (title, idx, len(pages))
            page_subtitle = subtitle
            range_text = "照片 %d～%d" % (start, end)
            page_subtitle = (page_subtitle + "｜" + range_text) if page_subtitle else range_text

            if detail_auto:
                detail_title = pick(a, cfg, "detail_title", None) or ("详图（1:%d）" % nice_scale(dw))
                if "1:" not in page_subtitle and detail_title.startswith("详图"):
                    page_subtitle += "｜" + detail_title
            else:
                detail_title = pick(a, cfg, "detail_title", "详图（1:800）")
            zone_title = pick(a, cfg, "zone_title", "分区图（反索引）")
            total_title = pick(a, cfg, "total_title", "总图（反索引）")

            jpg = page_dir / "详图_A3_12张.jpg"
            pdf = page_dir / "详图_A3_12张.pdf"
            cmd = [
                sys.executable, str(compose_script),
                "--map-dir", str(map_dir),
                "--meta", str(page_meta),
                "--photo-dir", str(photo_dir),
                "--out", str(jpg),
                "--pdf", str(pdf),
                "--title", page_title,
                "--subtitle", page_subtitle,
                "--detail-title", detail_title,
                "--zone-title", zone_title,
                "--total-title", total_title,
                "--photos-per-page", str(photos_per_page),
            ]
            if scale_auto:
                cmd += ["--scale-auto"]
            print("[%d/%d] compose A3" % (idx, len(pages)))
            subprocess.run(cmd, check=True)
            page_pdfs.append(pdf)

        merge_pdfs(page_pdfs, final_pdf)
        print("DONE final:", final_pdf)
        if not cleanup:
            print("KEPT work:", work_root)
    except Exception:
        print("FAILED; temp kept for diagnosis:", work_root, file=sys.stderr)
        raise


if __name__ == "__main__":
    main()

