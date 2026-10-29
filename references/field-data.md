# 六只脚抓取接口说明（实测 2026-10-12）

> 前提：这些接口基本是公开的，无需登录。个别行程的照片只在旧版足迹接口里返回。

## 1. 轨迹（GPS 航迹点）

```
GET https://www.foooooot.com/v4/api/trip/{tripId}/trackjson
```

返回：数组的数组，形如 `[[ [t, lat, lon, ele, speed, dist], ... ]]`（外层是分段，内层是点）。
- `t`：Unix 时间戳（秒）
- `lat` / `lon`：WGS84 经纬度
- `ele`：高程（米）
- `speed`：速度
- `dist`：累计里程

## 2. 行程信息

```
GET https://www.foooooot.com/api/v3/trip/{tripId}/?richtxt=1
```

关键字段：`name`、`start_place_name` / `end_place_name`、`distance`、`duration`、
`elevation_min` / `elevation_max`、`speed_max` / `speed_mean`、`occurtime`、`activity`、`sketch_url`。

## 3. 脚印 / 相片

优先用旧版接口（返回照片直链）：

```
GET https://www.foooooot.com/trip/{tripId}/footprintsjson/
GET https://www.foooooot.com/trip/{tripId}/offsetfootprintsjson/    # 同上，坐标略有差异
```

每条记录形如：
`[时间, lat, lon, ele, 序号, 缩略图URL, 图库URL, "", "pic", 0, 编辑URL, 详情URL]`

**取原图**：把 `-.gallery`（或 `-.thumbnail`）后缀去掉即可拿到原始大图，例如
`.../152539_133E0.jpg-.gallery` → `.../152539_133E0.jpg`。

> 备选：`GET /api/v3/trip/{tripId}/footprint/?page_num=1&page_size=50`。
> 实测该接口对老行程常返回空 `data: []`，**以 `footprintsjson` 为准**；两处都空才是真的没有相片。

## 4. 经验

- 请求带头 `Referer: https://www.foooooot.com/trip/{tripId}/` 与普通浏览器 UA 即可。
- 抓之前先看 `footprintsjson` 长度：为 `[]` 说明该行程没传相片（很多老行程如此）。
- 相片普遍带 GPS，可直接用于「影像信息表」里的拍摄位置。
- 抓取后的原始照片只用于 `archive_photos.py` 归档；归档完成后可删除原始照片目录，保留 `照片归档/`、`meta_archived.json` 和 `照片索引.csv` 即可支撑后续图册与报告。
