# 校园全景图库（瓦片化浏览 · DJI 导入）

日期：2026-10-10 · 与站管协作

> **修订（2026-10-12）：每级改为一整幅层级图，取消 512px 网格切片。**
> 决策 2 原按 512px 网格切片（`<z>/<y>/<x>.jpg`）并配 `{z}/{y}/{x}` 取片模板。实测
> Marzipano `EquirectGeometry` 的取片单位是「一层一整张等距柱状图」——`EquirectTile`
> 只携带 `z`，URL 模板只认 `{z}` 占位符（marzipano 0.10.2 源码
> `src/geometries/Equirect.js` / `src/sources/ImageUrl.js`）；网格记法下 `{y}`/`{x}`
> 被替换为空串（请求形态 `…/1//.jpg`），线上取片全量 404。现改为每级落一张
> `<z>.jpg`，模板只含 `{z}`；`tile_size` 字段与 `cols`/`rows` 网格元数据随之下线。
> 首屏与渐进加载行为不变；立方体重采样路线维持「被否的方案」原判（不引入 numpy）。
> **运维补充**：既有记录需经「重新切片」重建为新的产物形态——管理页逐条「重新切片」、
> 调 `reprocess` 接口、或 shell 批量 `process_panorama`（保留记录 ID 与手工调整）；
> `import_static_panoramas --force` 走「删旧建新」，ID 会变号、手工调整（如 initial 视角）会丢，
> 仅在确认那些记录无手工改动时可用。

## 背景与问题

「校园一览」下方的「校园全景图」按钮原先指向一个手写静态页 `static/panorama/index.html`：7 个 Marzipano 场景，每个直接加载 `pano_N.jpg`（4.7–8.7MB，合计约 50MB），并用 `EquirectGeometry([{ width: 10000, height: 5000 }])` 声明一个与源图实际尺寸未必相符的**单层**几何。实测慢、移动端白屏，根因三条：

1. **整张原图直出**——首屏必须下完一张 8MB 图才有画面；
2. **无层级**——~50MP 巨图一次性交给 WebGL / CSS 舞台，移动端 GPU 纹理上限（常为 4096）直接超限；
3. **无缓存语义**——静态素材随 `static/` 发版，但并未按内容寻址，改图即全网重下。

同时业务侧提出三项需求：**加载要快**、**有权限的用户可增删改**、**能导入 DJI 无人机自动合成的全景图并自动适配展示**。

## 决策

1. **新 `panorama` 应用，图库入库。** 全景图成为独立门户内容，不再借用 `about.panorama_url` 外链，也不再是「仓库里的静态素材」。`Panorama` 模型持有原图（存档）、瓦片目录、预览 / 缩略图、切片状态与来源元数据。
2. **浏览路径只吃瓦片。** 导入时生成等距柱状多级金字塔（层级宽 1024/2048/4096/8192，512px 瓦片，切片阶段封顶 8192）+ 低清预览（~1024×512）+ 缩略图（~640×320），落 `MEDIA_ROOT/panorama/…` 由 nginx 直供。首屏只需最小层两张瓦片（~90KB），细节层随视野按需补齐，`pinFirstLevel` 让最小层常驻打底。
   - **原图永不进浏览路径**：它是存档与重切片的输入，只对持 `panorama.manage_panoramas` 者返回 `source_url`。
3. **切片同步做，不引入队列。** 本项目部署规模下 8192×4096 全量切片约数秒；换来「无后台任务框架、无悬挂状态」。失败**不丢记录**：置 `status=failed` + `error`，走 `POST /panorama/panoramas/{id}/reprocess/` 或管理命令重来。
4. **权限：一个命名工作流权限 `panorama.manage_panoramas` 管增 / 删 / 改 / 重切。** 读不门禁权限，走「身份 + 可见性」（公开侧只出 `is_published` 且 `status=ready`），管理者可见全部（含切片中 / 失败）——与 ADR-0005 决策 8 的读谱系一致；前端能力键 `can_manage_panoramas`。
   - 不按 Django CRUD 拆三件套：全景图的增 / 删 / 改由同一批人持有，也不构成独立审计面（ADR-0005 决策 5 三条触发均不满足）。
5. **DJI 导入 = 识别 + 适配，不做拼接。** DJI Fly / DJI GO 4 的「球面 / Sphere」输出就是 2:1 等距柱状 JPEG，APP1 段里带 `GPano:*` 与 `drone-dji:*`。导入时：
   - 校验宽高比 2:1（±5%）且 GPano 未报裁切 → 否则以面向使用者的措辞拒绝（点名「球面 / Sphere」模式，而不是丢一句「格式错误」）；
   - 读 `GPano:PoseHeadingDegrees`（或回落 `drone-dji:GimbalYawDegree`）得**拍摄朝向**；读 `InitialViewHeading/Pitch/VerticalFovDegrees` 得**初始视角**，折算成 viewer 的初始 yaw / pitch / fov（yaw 以原图水平中心为 0，角度归一化到 ±180°并夹到合理区间）；
   - 记 `origin=dji`、`device_model`（EXIF 缺失时回落 `drone-dji:Model`）与元数据快照（GPano + drone-dji 全量），便于事后追溯与重适配。
   - **不做多张鱼眼拼接**：那需要外部拼接器（hugin / PTGui 等），不属本站职责；站点只接受「已合成好的全景图」。
6. **zip 只是传输外壳。** DJI 导出常是文件夹 / 压缩包，故允许上传 zip：服务端解包、挑出包内最合适的一张（优先 2:1，其次面积最大），落进 media 后**丢弃压缩包**——压缩包从不持久化。不用 `extractall`（结构上消除 zip-slip 路径穿越的利用面），并按「同步上传上限 × 4」封顶解压总量（防 zip bomb）。

## 被否的方案

- **只降采样、不做瓦片**：改一行代码，但 8MB → 2MB 仍是一次性整图 + 单层纹理，移动端纹理上限问题没解决。否。
- **改用立方体贴图（cube）瓦片**：质量与取片数更优，但等距柱状 → 立方体需要逐像素重采样；纯 Pillow 下要么太慢要么得引入 numpy，收益不抵复杂度。等距柱状瓦片 + `pinFirstLevel` 已达目标。否。
- **引入 Celery / 队列做异步切片**：本项目只有 SQLite + 单机 Gunicorn，为一个几秒的任务引入队列与额外运维面不合算。否。
- **继续用 `about.panorama_url` 外链**：满足不了「站内可增删改」与「导入即自动适配」。否。
- **在 Django admin 里直接新增 Panorama**：后台表单不会跑切片流水线，只会产出无瓦片的坏记录；后台因此设为「不可新增、只读查看 + 微调」。否。
- **新建 SiteSettings 旋钮控制全景图上传上限**：已有「同步上传单文件上限」语义完全一致，直接复用，不新增旋钮（ADR-0010 的最小旋钮面）。否。

## 后果

- 新增 `panorama` 应用与迁移；生产部署需 `migrate`，并确认 nginx 的 `client_max_body_size` ≥ 站点同步上传上限，且 `/media/panorama/` 带长缓存。
- 既有 7 张静态素材由 `manage.py import_static_panoramas` 导入并重切片；`static/panorama/`、`scripts/check_panorama_static.py`、`scripts/pack-release.sh` 里的既有防线**暂不删除**——静态页作为兜底保留，待新全景浏览页上线并验证后再单独下线（另开变更）。
- 瓦片随记录删除回收（`post_delete` + 递归删目录）；`media/` 已被 `.gitignore` 覆盖，不新增忽略项。
- 初始 yaw 的**绝对取向**（`InitialViewHeadingDegrees` 是否已在原图坐标系内）需在真机 DJI 素材上核对一次；因此 `initial_yaw` / `initial_pitch` / `initial_fov` 保持可写，发现偏差可直接改，无需重传原图。前端全景浏览页与管理页见 PR②。
