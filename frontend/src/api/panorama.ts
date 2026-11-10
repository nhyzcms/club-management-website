import { createRequest } from "./shared";
import type { Paginated } from "../types/pagination";
import type { PanoramaDetail, PanoramaEditable, PanoramaListItem } from "../types/panorama";

const request = createRequest("/panorama");

/**
 * 拉全列表（浏览页与管理页都要）。列表分页 20/ 页，逐页翻到 `next` 为空；
 * 另加 10 页硬上限作防御（内容封顶 200 条，这是个校园全景图库，不会更大）。
 */
async function listAll(): Promise<PanoramaListItem[]> {
  const all: PanoramaListItem[] = [];
  for (let page = 1; page <= 10; page += 1) {
    const envelope = (await request(`/panoramas/?page=${page}`)) as Paginated<PanoramaListItem>;
    all.push(...(envelope.results ?? []));
    if (!envelope.next) break;
  }
  return all;
}

export const panoramaApi = {
  listAll,

  get: (id: number) => request(`/panoramas/${id}/`) as Promise<PanoramaDetail>,

  /**
   * 导入一张全景图（multipart）。`source` 可以是等距柱状 JPEG/PNG/WebP，
   * 也可以是装着全景图的 zip（服务端解包挑图后丢弃压缩包）。
   * 服务端**同步**切片，大图可能阻塞数秒（8192×4096 实测约 4 秒）。
   */
  create: (data: FormData) =>
    request("/panoramas/", { method: "POST", body: data }) as Promise<PanoramaDetail>,

  update: (id: number, data: PanoramaEditable) =>
    request(`/panoramas/${id}/`, {
      method: "PATCH",
      body: JSON.stringify(data),
    }) as Promise<PanoramaDetail>,

  remove: (id: number) => request(`/panoramas/${id}/`, { method: "DELETE" }) as Promise<null>,

  /** 用存档原图重新切片（切片失败 / 想重调层级时用，不需重传原图）。 */
  reprocess: (id: number) =>
    request(`/panoramas/${id}/reprocess/`, { method: "POST" }) as Promise<PanoramaDetail>,
};
