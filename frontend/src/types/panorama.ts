/**
 * 校园全景图：与 `panorama` 应用序列化器一一对应的前端类型。
 *
 * 契约来源：docs/api/panorama.md（列表 / 详情字段）与 docs/adr/0022-campus-panorama-library.md。
 */

/** 切片状态：processing（切片中）/ ready（可浏览）/ failed（切片失败）。 */
export type PanoramaStatus = "processing" | "ready" | "failed";

/** 来源：手动上传 / DJI 全景图导入 / 静态素材导入。 */
export type PanoramaOrigin = "upload" | "dji" | "import";

/** 一个层级（z=0 最小、越大越清晰；每级一整幅图）；与后端 `tile_levels` 单项同形。 */
export interface PanoramaTileLevel {
  z: number;
  width: number;
  height: number;
}

/** 列表项（`GET /panorama/panoramas/`）。 */
export interface PanoramaListItem {
  id: number;
  title: string;
  description: string;
  order: number;
  is_published: boolean;
  status: PanoramaStatus;
  width: number;
  height: number;
  origin: PanoramaOrigin;
  device_model: string;
  capture_heading: number | null;
  thumb_url: string | null;
  preview_url: string | null;
  created_at: string;
  updated_at: string;
}

/** 详情（`GET /panorama/panoramas/{id}/`）：多出取片模板、层级表与初始视角。 */
export interface PanoramaDetail extends PanoramaListItem {
  error: string;
  projection: string;
  source_name: string;
  source_bytes: number;
  initial_yaw: number;
  initial_pitch: number;
  initial_fov: number;
  tile_levels: PanoramaTileLevel[];
  /** Marzipano 取片模板，含 `{z}`（层级索引）占位符；未切片完成为 null。 */
  tile_url_template: string | null;
  /** 存档原图地址；仅持管理权限者可见，其余为 null。 */
  source_url: string | null;
  metadata: Record<string, any>;
  created_by: number | null;
}

/** 可写字段集——与后端 `PanoramaDetailSerializer` 的可写集保持一致。 */
export interface PanoramaEditable {
  title?: string;
  description?: string;
  order?: number;
  is_published?: boolean;
  initial_yaw?: number;
  initial_pitch?: number;
  initial_fov?: number;
}

export const PANORAMA_STATUS_LABELS: Record<PanoramaStatus, string> = {
  processing: "切片中",
  ready: "可浏览",
  failed: "切片失败",
};

export const PANORAMA_ORIGIN_LABELS: Record<PanoramaOrigin, string> = {
  upload: "手动上传",
  dji: "DJI 导入",
  import: "静态导入",
};

/** 文件选择器接受的文件类型（与后端 services 的 IMAGE_EXTENSIONS / ARCHIVE_EXTENSIONS 对齐）。 */
export const PANORAMA_ACCEPT = ".jpg,.jpeg,.png,.webp,.zip";
