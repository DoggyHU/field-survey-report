#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把选定照片归档并按图册编号重命名。

输入 meta.json（含 file/lat/lon，可选 i）和照片目录，输出：
    归档照片/1_p03.jpg, 2_p04.jpg ...
    照片索引.csv
    meta_archived.json

规则：
- 图册显示编号为 1、2、3…；归档文件名用同一个数字：1_p03.jpg。
- 不生成 1-1、2-1 这种“分幅号-张号”。
- 原图保留不动，归档是复制。归档完成后，若不再需要重新归档，可删除原始照片目录；后续只用归档目录和 meta_archived.json。
"""
import argparse, csv, datetime, json, os, re, shutil
from pathlib import Path


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def pick_value(fp, idx):
    if not fp:
        return "", "", ""
    # 六只脚 footprints: [time, lat, lon, ele, seq, thumb, gallery, ...]
    if isinstance(fp, (list, tuple)) and len(fp) >= 3:
        return fp[0], fp[1], fp[2]
    return "", "", ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--meta", required=True, help="选定照片 JSON，含 file/lat/lon")
    ap.add_argument("--photo-dir", required=True, help="原图目录（meta.file 所在目录）")
    ap.add_argument("--out-dir", default="", help="归档目录；默认 <photo-dir>/已归档")
    ap.add_argument("--footprints", default="", help="可选，脚印 JSON，用于补拍摄时间")
    ap.add_argument("--start-index", type=int, default=1)
    ap.add_argument("--strip-prefix", default="",
                    help="去掉下载名的批次前缀，如 P 可把 P01_100126_239D1.jpg 归档成 1_100126_239d1.jpg")
    a = ap.parse_args()

    meta = load_json(a.meta)
    fps = load_json(a.footprints) if a.footprints else []
    photo_dir = Path(a.photo_dir)
    out_dir = Path(a.out_dir) if a.out_dir else photo_dir / "已归档"
    out_dir.mkdir(parents=True, exist_ok=True)

    archived = []
    rows = []
    for k, m in enumerate(meta):
        seq = a.start_index + k
        src_name = m["file"]
        src = photo_dir / src_name
        if not src.exists():
            raise FileNotFoundError("找不到照片：%s" % src)

        stem = Path(src_name).stem
        if a.strip_prefix:
            # 前缀大小写不敏感：抓取脚本落地名是 P01_xxx，这里可能已做过小写处理
            stem = re.sub(r"^%s\d+_" % re.escape(a.strip_prefix), "", stem, flags=re.I)
        stem = stem.lower()
        suffix = Path(src_name).suffix.lower() or ".jpg"
        dst_name = "%d_%s%s" % (seq, stem, suffix)
        dst = out_dir / dst_name
        shutil.copy2(src, dst)

        fp = None
        idx = m.get("i")
        # 六只脚 meta 里的 i 是 1-based 序号；footprints 数组是 0-based。
        if isinstance(idx, int) and 1 <= idx <= len(fps):
            fp = fps[idx - 1]
        elif k < len(fps):
            fp = fps[k]
        ts, lat, lon = pick_value(fp, k)
        if not lat:
            lat, lon = m.get("lat", ""), m.get("lon", "")
        ts_text = ""
        if ts not in ("", None):
            try:
                ts_text = datetime.datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                ts_text = str(ts)

        archived.append({
            "file": dst_name,
            "orig_file": src_name,
            "seq": seq,
            "lat": lat,
            "lon": lon,
            "time": ts_text,
        })
        rows.append([seq, dst_name, src_name, ts_text, lat, lon, ""])

    with open(out_dir / "meta_archived.json", "w", encoding="utf-8") as f:
        json.dump(archived, f, ensure_ascii=False, indent=2)

    with open(out_dir / "照片索引.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["序号", "归档文件名", "原文件名", "拍摄时间", "纬度", "经度", "内容"])
        w.writerows(rows)

    print("archived %d photos -> %s" % (len(archived), out_dir))
    print("index:", out_dir / "照片索引.csv")
    print("meta:", out_dir / "meta_archived.json")


if __name__ == "__main__":
    main()
