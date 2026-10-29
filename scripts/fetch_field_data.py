#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""六只脚行程抓取 + 轨迹格式转换（field-survey-report skill）

用法:
    python fetch_field_data.py --trip 4566590 --out ./outputs
    python fetch_field_data.py --trip 4566590 --trip 2411186 --out ./outputs

每个行程产出到 <out>/<trip>_<名称>/ :
    01_原始数据/  行程信息.json  原始轨迹.json  脚印.json
    02_轨迹成果/  .kml  _gxtrack.kml  .gpx  .plt
    03_现场影像/  P01_*.jpg ...
"""
import argparse, json, os, re, math, datetime, urllib.request

BASE = "https://www.foooooot.com"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120 Safari/537.36")

def _get(url, referer=None):
    h = {"User-Agent": UA}
    if referer:
        h["Referer"] = referer
    return urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=60).read()

def _json(url, referer=None):
    return json.loads(_get(url, referer).decode("utf-8"))

def fetch(trip):
    ref = BASE + "/trip/%s/" % trip
    info = _json(BASE + "/api/v3/trip/%s/?richtxt=1" % trip, ref).get("data", {})
    track = _json(BASE + "/v4/api/trip/%s/trackjson" % trip, ref)
    try:
        fps = _json(BASE + "/trip/%s/footprintsjson/" % trip, ref)
    except Exception:
        fps = []
    return info, track, fps

def points(track):
    segs = track if isinstance(track[0][0], list) else [track]
    return [p for s in segs for p in s]

def utc(ts):
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc)

def write_tracks(pts, outdir, name):
    line = "\n".join("%.8f,%.8f,%.2f" % (lon, lat, ele) for t, lat, lon, ele, sp, d in pts)
    t0, t1 = pts[0], pts[-1]
    kml = ('<?xml version="1.0" encoding="UTF-8"?>\n'
           '<kml xmlns="http://www.opengis.net/kml/2.2"><Document><name>%s</name>\n'
           '<Style id="l"><LineStyle><color>ff2222ff</color><width>4</width></LineStyle></Style>\n'
           '<Placemark><name>轨迹</name><styleUrl>#l</styleUrl><LineString><tessellate>1</tessellate>'
           '<altitudeMode>clampToGround</altitudeMode><coordinates>\n%s\n</coordinates></LineString></Placemark>\n'
           '<Placemark><name>起点</name><Point><coordinates>%.8f,%.8f,%.2f</coordinates></Point></Placemark>\n'
           '<Placemark><name>终点</name><Point><coordinates>%.8f,%.8f,%.2f</coordinates></Point></Placemark>\n'
           '</Document></kml>\n') % (name, line, t0[2], t0[1], t0[3], t1[2], t1[1], t1[3])
    open(os.path.join(outdir, name + ".kml"), "w", encoding="utf-8").write(kml)

    whens = "\n".join("  <when>%sZ</when>" % utc(t).strftime("%Y-%m-%dT%H:%M:%S") for t, *_ in pts)
    gco = "\n".join("  <gx:coord>%.8f %.8f %.2f</gx:coord>" % (lon, lat, ele) for t, lat, lon, ele, sp, d in pts)
    gx = ('<?xml version="1.0" encoding="UTF-8"?>\n'
          '<kml xmlns="http://www.opengis.net/kml/2.2" xmlns:gx="http://www.google.com/kml/ext/2.2">'
          '<Document><name>%s</name><Placemark><gx:Track>\n%s\n%s\n</gx:Track></Placemark></Document></kml>\n') % (name, whens, gco)
    open(os.path.join(outdir, name + "_gxtrack.kml"), "w", encoding="utf-8").write(gx)

    tp = "\n".join('  <trkpt lat="%.8f" lon="%.8f"><ele>%.2f</ele><time>%sZ</time></trkpt>'
                   % (lat, lon, ele, utc(t).strftime("%Y-%m-%dT%H:%M:%S")) for t, lat, lon, ele, sp, d in pts)
    gpx = ('<?xml version="1.0" encoding="UTF-8"?>\n<gpx version="1.1" creator="field-survey-report" '
           'xmlns="http://www.topografix.com/GPX/1/1"><trk><name>%s</name><trkseg>\n%s\n</trkseg></trk></gpx>\n') % (name, tp)
    open(os.path.join(outdir, name + ".gpx"), "w", encoding="utf-8").write(gpx)

    L = ["OziExplorer Track Point File Version 2.1", "WGS 84", "Altitude is in Feet", "Reserved 3",
         "0,2,255,%s,0,0,2,8421376" % name, str(len(pts))]
    for t, lat, lon, ele, sp, d in pts:
        ser = t / 86400.0 + 25569.0
        day = int(math.floor(ser)); frac = ser - day
        L.append("%.8f,%.8f,0,%.1f,%.0f,%.8f" % (lat, lon, ele * 3.280839895, day, frac))
    open(os.path.join(outdir, name + ".plt"), "w", encoding="utf-8").write("\n".join(L) + "\n")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trip", action="append", required=True, help="六只脚行程号，可重复")
    ap.add_argument("--out", default="./outputs")
    ap.add_argument("--no-photos", action="store_true")
    a = ap.parse_args()
    for trip in a.trip:
        info, track, fps = fetch(trip)
        pts = points(track)
        raw = (info.get("name") or str(trip)).strip()
        label = re.sub(r'[\\/:*?"<>|\r\n\t]+', "_", raw).strip("_ ") or str(trip)
        d = os.path.join(a.out, "%s_%s" % (trip, label))
        for sub in ("01_原始数据", "02_轨迹成果", "03_现场影像"):
            os.makedirs(os.path.join(d, sub), exist_ok=True)
        json.dump(info, open(os.path.join(d, "01_原始数据", "行程信息.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        json.dump(track, open(os.path.join(d, "01_原始数据", "原始轨迹.json"), "w", encoding="utf-8"), ensure_ascii=False)
        json.dump(fps, open(os.path.join(d, "01_原始数据", "脚印.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        write_tracks(pts, os.path.join(d, "02_轨迹成果"), "%s_%s" % (trip, label))
        n = 0
        if not a.no_photos:
            for i, fp in enumerate(fps, 1):
                url = str(fp[6]).replace("-.gallery", "").replace("-.thumbnail", "")
                # 2026-10-28：新版图库原图 URL 没有扩展名（…/49c8fa25….jpg-.gallery 去掉后缀
                # 后就是 …/49c8fa25…，Content-Type 仍是 image/jpeg）。按扩展名过滤会把
                # 整条行程的照片全丢掉（实测 163 张全部跳过），故改为只排除默认占位图，
                # 缺失扩展名时补 .jpg。
                if "defaultfootprintpic" in url:
                    continue
                base = os.path.basename(url.split("?")[0]) or ("P%02d" % i)
                if not base.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
                    base += ".jpg"
                try:
                    data = _get(url, BASE + "/trip/%s/" % trip)
                except Exception as e:
                    print("  photo fail", url, e); continue
                open(os.path.join(d, "03_现场影像", "P%02d_%s" % (i, base)), "wb").write(data)
                n += 1
        print("[%s] %s: %d pts, %d footprints, %d photos -> %s" % (trip, label, len(pts), len(fps), n, d))

if __name__ == "__main__":
    main()
