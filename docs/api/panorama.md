# 校园全景图 API

校园全景图库：把等距柱状（equirectangular）全景图入库，导入时自动切出多级层级图 + 低清预览，浏览侧只吃层级图。支持直接上传 DJI（DJI Fly / DJI GO 4）合成的球面全景，也支持上传装着全景图的 **zip**（解包挑图后即丢弃压缩包）。

> 全局约定（认证 / 错误 / 分页 / CSRF）见 [API 总览](README.md)。相关设计记录：[ADR-0022](../adr/0022-campus-panorama-library.md)（瓦片化浏览 · DJI 导入）、[ADR-0005](../adr/0005-access-control-principle.md)（`has_perm` 判权）

挂载：`config/urls.py` 的 `panorama/` + app 内 router 前缀 `panoramas`，路径均为 `/panorama/panoramas/…`。列表响应为 DRF 分页信封（`PAGE_SIZE=20`）。

## 为什么分层取片

原静态全景页把 5~8MB 的整张原图交给 WebGL，移动端 GPU 纹理上限（4096 / 8192）直接超限。现在导入即切出：

| 产物 | 位置 | 用途 |
|---|---|---|
| 原图（存档） | `/media/panorama/sources/<uuid>.jpg` | 重切片输入；**不在浏览路径上**，仅管理者可见 `source_url` |
| 层级图 | `/media/panorama/tiles/<uuid>/<z>.jpg` | 浏览主体，每级一整幅等距柱状图，`z` 从 0（最小层）递增 |
| 预览图 | `/media/panorama/assets/preview-<uuid>.jpg` | 最小层整幅（~1024×512），首屏兜底 / 分享图 |
| 缩略图 | `/media/panorama/assets/thumb-<uuid>.jpg` | 列表卡片（~640×320） |

后台规则：层级宽度取 2 的幂（1024 / 2048 / 4096 / 8192）且不超过源图宽度，比 1024 还窄的源图就用原宽；分层阶段封顶 8192（更宽的源图降采样，原图仍完整存档）。

每级落**一整幅**等距柱状图（而不是 512px 网格）：Marzipano `EquirectGeometry` 的取片单位就是「一层一张图」——`EquirectTile` 只携带 `z`，取片模板只认 `{z}` 占位符；网格记法（`{z}/{y}/{x}`）属立方体贴图，套用会让 `{y}`/`{x}` 被替换为空串（请求形态 `…/1//.jpg`）而全量 404。详见 [ADR-0022 修订](../adr/0022-campus-panorama-library.md)。

## 端点一览

| 方法 | 路径 | 认证 | 权限 | 说明 |
|---|---|---|---|---|
| GET | /panorama/panoramas/ | 公开 | — | 全景图列表（仅已发布且可浏览），分页 |
| POST | /panorama/panoramas/ | 登录 | `panorama.manage_panoramas` | 导入全景图（multipart：图片或 zip） |
| GET | /panorama/panoramas/{id}/ | 公开 | — | 详情（含取片模板 / 层级表 / 初始视角） |
| PUT / PATCH | /panorama/panoramas/{id}/ | 登录 | `panorama.manage_panoramas` | 改标题 / 描述 / 排序 / 公开 / 初始视角 |
| DELETE | /panorama/panoramas/{id}/ | 登录 | `panorama.manage_panoramas` | 删除，连瓦片一起回收 |
| POST | /panorama/panoramas/{id}/reprocess/ | 登录 | `panorama.manage_panoramas` | 用存档原图重新切片 |

**可见性**（读走「身份 + 可见性」，不门禁权限，[ADR-0005](../adr/0005-access-control-principle.md) 决策 8）：公开侧只返回 `is_published=true` **且** `status=ready` 的条目；持 `panorama.manage_panoramas` 者可见全部（含 `processing` / `failed`）。

**切片状态机**（非访问控制，由流水线写）：`processing`（创建后短暂停留）→ `ready` / `failed`。失败不丢记录，带 `error` 供排查，可 `reprocess`。

## 端点详情

### 全景图列表
`GET /panorama/panoramas/`

**认证**：公开；**权限**：—

**查询参数**

| 名称 | 类型 | 必填 | 说明 |
|---|---|---|---|
| page | 整数 | 否 | 页码（每页 20 条） |
| search | 字符串 | 否 | 模糊匹配 `title` / `description` / `device_model` |
| ordering | 字符串 | 否 | `order` / `created_at` / `updated_at`，前缀 `-` 倒序；默认 `order, -created_at` |
| origin | 字符串 | 否 | `upload` / `dji` / `import` |
| status | 字符串 | 否 | `processing` / `ready` / `failed`（公开侧已收窄为 `ready`，此参数对匿名无额外作用） |

**响应 `200 OK`**

```json
{
  "count": 2,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": 3,
      "title": "操场",
      "description": "春季运动会前拍摄。",
      "order": 1,
      "is_published": true,
      "status": "ready",
      "width": 8192,
      "height": 4096,
      "origin": "dji",
      "device_model": "FC7303",
      "capture_heading": 128.5,
      "thumb_url": "https://8.153.145.175/media/panorama/assets/thumb-1f3c9a.jpg",
      "preview_url": "https://8.153.145.175/media/panorama/assets/preview-5b7e21.jpg",
      "created_at": "2026-10-10T12:00:00Z",
      "updated_at": "2026-10-10T12:00:03Z"
    }
  ]
}
```

### 导入全景图
`POST /panorama/panoramas/`

**认证**：登录；**权限**：`panorama.manage_panoramas`

**请求体**（`multipart/form-data`）

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| title | 字符串 | 是 | 非空白；超 200 字符截断 |
| source（或 `file`） | 文件 | 是 | 等距柱状全景图（JPEG / PNG / WebP），**或**装着全景图的 `.zip` |
| description | 字符串 | 否 | 超 2000 字符截断 |
| order | 整数 | 否 | 排序，钳到 0~9999 |
| is_published | 布尔串 | 否 | 缺省 `true`；`0` / `false` / `no` / `off` 视为不公开 |

**准入规则**

| 规则 | 不满足时 |
|---|---|
| 大小 ≤ 站点策略的「同步上传单文件上限」（默认 50MB） | 400 `too_large` |
| 宽高比 2:1（±5%）且 GPano 未报裁切 | 400 `not_equirectangular` |
| 像素数 ≤ 2 亿 | 400 `too_many_pixels` |
| zip 内至少有一张可识别图片，解压总量 ≤ 同步上限 × 4 | 400 `no_image_in_archive` / `archive_too_large` |

**响应 `201 Created`**

```json
{
  "id": 3,
  "title": "操场",
  "description": "",
  "order": 1,
  "is_published": true,
  "status": "ready",
  "error": "",
  "origin": "dji",
  "device_model": "FC7303",
  "metadata": {
    "make": "DJI", "model": "FC7303", "projection": "equirectangular",
    "full_pano_width": 8192, "cropped_area_width": 8192,
    "gpano": {"GPano:PoseHeadingDegrees": "128.5", "GPano:InitialViewHeadingDegrees": "150"},
    "dji": {"drone-dji:GimbalYawDegree": "128.5", "drone-dji:Model": "FC7303"}
  },
  "width": 8192,
  "height": 4096,
  "projection": "equirectangular",
  "source_name": "DJI_0001.JPG",
  "source_bytes": 8388608,
  "initial_yaw": 21.5,
  "initial_pitch": -8.0,
  "initial_fov": 75.0,
  "capture_heading": 128.5,
  "tile_levels": [
    {"z": 0, "width": 1024, "height": 512},
    {"z": 1, "width": 2048, "height": 1024},
    {"z": 2, "width": 4096, "height": 2048},
    {"z": 3, "width": 8192, "height": 4096}
  ],
  "tile_url_template": "https://8.153.145.175/media/panorama/tiles/9c31d0e8/{z}.jpg",
  "preview_url": "https://8.153.145.175/media/panorama/assets/preview-5b7e21.jpg",
  "thumb_url": "https://8.153.145.175/media/panorama/assets/thumb-1f3c9a.jpg",
  "source_url": "https://8.153.145.175/media/panorama/sources/4d2a77be.jpg",
  "created_by": 7,
  "created_at": "2026-10-10T12:00:00Z",
  "updated_at": "2026-10-10T12:00:03Z"
}
```

`source_url` 仅对持 `panorama.manage_panoramas` 者返回（字段掩码），其余人为 `null`。
`status` 可能是 `failed`（切片失败）——此时记录已建、HTTP 仍为 201，请读 `error` 并调 `reprocess`。

**错误**

| 状态码 | 场景（`reason`） |
|---|---|
| 400 | 未带 `source`；`title` 为空；`too_large` / `unknown_format` / `unsupported_image` / `not_equirectangular` / `too_many_pixels` / `empty_file` / `bad_zip` / `no_image_in_archive` / `archive_too_large` / `unreadable_image` |
| 403 | 匿名，或未持 `panorama.manage_panoramas` |

### 全景图详情
`GET /panorama/panoramas/{id}/`

**认证**：公开；**权限**：—

未发布或未就绪的条目对公众返回 `404`；管理者可正常读取（用于管理列表）。
取片模板中的 `{z}`（层级索引）由前端替换——与 Marzipano `EquirectGeometry` 的取片约定一致：每层一整幅图，模板只认 `{z}`。

**响应 `200 OK`**：同创建响应结构。

### 编辑全景图
`PUT /panorama/panoramas/{id}/`、`PATCH /panorama/panoramas/{id}/`

**认证**：登录；**权限**：`panorama.manage_panoramas`

**可写字段**：`title` / `description` / `order` / `is_published` / `initial_yaw` / `initial_pitch` / `initial_fov`。
其余字段（尺寸、元数据、瓦片产物、`status`、`origin`、`source_*`）均只读——它们由切片流水线写。

`initial_*` 可写是故意的：DJI 素材的初始朝向已在服务端按 XMP 折算，若真机核对后发现偏了，管理者可直接改这三个值，**无需重传原图**。

**错误**：400 字段校验；403 无权限；404 不存在。

### 删除全景图
`DELETE /panorama/panoramas/{id}/`

**认证**：登录；**权限**：`panorama.manage_panoramas`

**响应 `204 No Content`**。级联回收磁盘产物：瓦片目录 + 预览图 + 缩略图（`post_delete` 信号，无定时任务）；原图同时删除。

### 重新切片
`POST /panorama/panoramas/{id}/reprocess/`

**认证**：登录；**权限**：`panorama.manage_panoramas`

用存档原图重跑流水线（换源图后、切片失败后、想重调层级）。先清旧产物再重建，`tile_dir` 会换新（旧目录已回收）。

**响应 `200 OK`**：详情结构（同上）。

**错误**

| 状态码 | 场景 |
|---|---|
| 400 | 该条目没有存档原图；或切片失败（`reason: processing_failed`，`detail` 带底层原因） |
| 403 | 无 `panorama.manage_panoramas` |
| 404 | 条目不存在 |

## 前端取片（Marzipano）

服务端只提供事实（层级表 + 模板），场景搭建在前端：

```js
const levels = pano.tile_levels.map((l) => ({ width: l.width }));
const source = Marzipano.ImageUrlSource.fromString(pano.tile_url_template);
const geometry = new Marzipano.EquirectGeometry(levels);
const limiter = Marzipano.RectilinearView.limit.traditional(pano.width, 100 * Math.PI / 180);
const view = new Marzipano.RectilinearView({
  yaw: pano.initial_yaw * Math.PI / 180,
  pitch: pano.initial_pitch * Math.PI / 180,
  fov: pano.initial_fov * Math.PI / 180,
}, limiter);
viewer.createScene({ source, geometry, view, pinFirstLevel: true });
```

`pinFirstLevel: true` 把最小层（`z=0`，一幅整图）常驻打底——这就是「秒出画面、细节渐进」的那一半；`preview_url` 可用于列表 / `og:image` / 加载前占位。

## 后台与运维

- **Django 后台**（`校园全景图 → 校园全景图`）：**不可新增**（后台表单不跑切片流水线），可查看全部字段并微调标题 / 描述 / 排序 / 公开 / 初始视角。上传入口在门户。
- **既有静态素材导入**：`uv run python manage.py import_static_panoramas [--dry-run] [--force] [--source-dir ...]`——幂等（按原文件名 + 来源跳过）。
- **nginx 侧**：瓦片与预览走 `/media/`，建议对 `/media/panorama/` 下 `Cache-Control: public, max-age=31536000, immutable`；`client_max_body_size` 不得低于站点「同步上传单文件上限」。
