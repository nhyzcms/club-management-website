import { afterEach, describe, expect, it, vi } from "vitest";
import { newsApi } from "../news";

const okJson = (data: unknown) =>
  ({ status: 200, ok: true, json: async () => data }) as unknown as Response;

describe("newsApi 请求接线（与后端路径契约一致）", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("uploadCover → POST /news/news/upload_cover/（image 字段）", async () => {
    const fetchMock = vi.fn(async () => okJson({ url: "http://x/media/news_covers/a.png" }));
    vi.stubGlobal("fetch", fetchMock);

    const file = new File(["x"], "cover.png", { type: "image/png" });
    const out = await newsApi.uploadCover(file);
    expect(out.url).toContain("/media/news_covers/");

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/news/news/upload_cover/");
    expect(init.method).toBe("POST");
    const body = init.body as FormData;
    expect(body).toBeInstanceOf(FormData);
    expect((body.get("image") as File).name).toBe("cover.png");
  });

  it("uploadImage → POST /news/news/upload_image/", async () => {
    const fetchMock = vi.fn(async () => okJson({ url: "http://x/media/news_content_images/a.png" }));
    vi.stubGlobal("fetch", fetchMock);

    await newsApi.uploadImage(new File(["x"], "inline.png", { type: "image/png" }));
    const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/news/news/upload_image/");
  });

  it("update → PATCH /news/news/{id}/", async () => {
    const fetchMock = vi.fn(async () => okJson({ id: 7 }));
    vi.stubGlobal("fetch", fetchMock);

    await newsApi.update(7, new FormData());
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/news/news/7/");
    expect(init.method).toBe("PATCH");
  });
});
