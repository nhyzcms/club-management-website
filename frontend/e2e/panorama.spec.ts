import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";
import { uniqueTitle } from "./utils";

/**
 * GitHub Actions 会把输出里的 `::error::` 行转成 check-run 标注，而标注可匿名读取。
 * 这让本用例在没有仓库日志权限的环境下也能把失败现场带出 CI。
 */
function annotateError(message: string) {
  console.log(`::error::${message.replace(/\s+/g, " ").slice(0, 900)}`);
}

/**
 * 在真实浏览器里现画一张 256×128（严格 2:1）JPEG。
 *
 * 特意不内联长 base64 常量：那种字符串抄错一个字符就变成「不是图片」，
 * 报错却在后端、很难定位；canvas.toDataURL 由浏览器保证产出合法 JPEG。
 * （既有 320×200 PNG 是 1.6:1，会被后端的 2:1 准入规则拒掉，不能复用。）
 */
async function makePanoramaJpeg(page: Page): Promise<Buffer> {
  const dataUrl = (await page.evaluate(() => {
    const canvas = document.createElement("canvas");
    canvas.width = 256;
    canvas.height = 128;
    const ctx = canvas.getContext("2d");
    if (ctx) {
      ctx.fillStyle = "#1c3a68";
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      for (let i = 0; i < 8; i += 1) {
        ctx.fillStyle = `hsl(${i * 40}, 55%, ${35 + i * 5}%)`;
        ctx.fillRect((canvas.width / 8) * i, 0, canvas.width / 16, canvas.height);
      }
    }
    return canvas.toDataURL("image/jpeg", 0.8);
  })) as string;
  return Buffer.from(dataUrl.split(",")[1], "base64");
}

/**
 * 校园全景图冒烟：管理页导入 → 层级图真能取到 → 浏览页能起来且取片 URL 正确。
 *
 * 断言分层（避免把用例绑在不确定的东西上）：
 * 1. **确定性**：走 UI 导入一张图，然后直接按接口给的 `tile_url_template`
 *    把 z=0 的层级图取一次，断言 200 且模板未被百分号转义 —— 不依赖 WebGL / 绘制。
 * 2. **结构性**：浏览页能打开、标题正确、渲染器脚本能加载（`window.Marzipano`）。
 * 3. **回归守卫**：查看器真实发出的取片必须 200，且 URL 不得含空路径段
 *    （`…/1//.jpg` 即 2026-10 线上 404 的畸形形态：模板混入 `{y}/{x}` 被替换为空串）。
 *    WebGL 不可用时走 CSS 舞台，同样会取图。
 *
 * 注意：全站是 hash 路由，页面地址必须写 `/#/...`；写成 `/panorama/...` 会被
 * Django 的 `panorama/` 路由接走（config/urls.py 已把该前缀从 SPA catch-all 排除）。
 *
 * 前置：`e2e_info` 在 seed_e2e 里是超管，故持有 `panorama.manage_panoramas`；
 * E2E 每个 run 重建数据库，库内初始为空，导入的那张就是浏览页的唯一场景。
 */
test.describe("校园全景图", () => {
  test("导入后层级图可访问（200），且取片模板未被百分号转义", async ({ page }) => {
    // 本用例比其它 UI 用例重：传图 → 服务端同步切片。默认 30s 只是「点几下」的预算。
    test.setTimeout(90_000);

    const title = uniqueTitle("E2E 全景");
    const watched: { url: string; status: number }[] = [];
    page.on("response", (res) => {
      const url = res.url();
      if (url.includes("/media/panorama/tiles/")) watched.push({ url, status: res.status() });
    });

    try {
      // ── 1. 管理页导入 ───────────────────────────────────────────
      await page.goto("/#/panorama/manage");
      await expect(page.getByRole("heading", { name: "管理校园全景图" })).toBeVisible();
      // 导入表单存在 = 能力门禁已放行（否则渲染的是无权限面板）
      await expect(page.getByRole("heading", { name: "导入全景图" })).toBeVisible();

      // SPA 启动时才拉取 csrftoken cookie（App 的 useEffect → GET /auth/csrf/）。
      // 不等它就提交，首次 POST 会被 Django 的 CSRF 校验挡下（403）。
      await page.waitForFunction(() => document.cookie.includes("csrftoken"));

      await page.setInputFiles('input[type="file"]', {
        name: "e2e-panorama.jpg",
        mimeType: "image/jpeg",
        buffer: await makePanoramaJpeg(page),
      });
      await page.getByPlaceholder("如：操场").fill(title);
      await page.getByRole("button", { name: "导入并切片" }).click();

      await expect(page.getByText(/已导入/)).toBeVisible({ timeout: 30_000 });
      await expect(page.locator(".pano-card-head strong")).toHaveText(title, { timeout: 10_000 });

      // ── 2. 接口层：层级图必须真能取到 200 ──────────────────────
      const origin = new URL(page.url()).origin;
      const listed = await (await page.request.get(`${origin}/panorama/panoramas/`)).json();
      expect(listed.count, `列表：${JSON.stringify(listed).slice(0, 300)}`).toBeGreaterThan(0);
      const id = listed.results[0].id;
      const detail = await (await page.request.get(`${origin}/panorama/panoramas/${id}/`)).json();
      expect(detail.status, `切片状态：${detail.status} / ${detail.error}`).toBe("ready");

      const template: string = detail.tile_url_template;
      // {z} 必须原样保留：build_absolute_uri 会把 { 转成 %7B，
      // Marzipano 按字面量替换占位符 → 一旦转义，线上取片全 404。
      // 且模板只能有 {z}：EquirectGeometry 每层一整幅图，{y}/{x}（立方体贴图记法）
      // 会被替换为空串 → `…/1//.jpg` 404（2026-10 线上事故；请求级回归守卫见第 3 步）。
      expect(template, `取片模板被百分号转义：${template}`).toContain("{z}.jpg");
      expect(template).not.toContain("%7B");
      expect(template).not.toContain("{y}");
      expect(template).not.toContain("{x}");

      const tileUrl = template.replace("{z}", "0");
      const tileRes = await page.request.get(tileUrl);
      expect(tileRes.status(), `层级图应 200：${tileUrl}`).toBe(200);
      expect((await tileRes.body()).length, `层级图不应为空：${tileUrl}`).toBeGreaterThan(0);

      // 预览图 / 缩略图同样要真的能取到
      for (const url of [detail.preview_url, detail.thumb_url]) {
        if (url) expect((await page.request.get(url)).status(), url).toBe(200);
      }

      // ── 3. 浏览页：打开、渲染器可加载、取片请求正确且成功（回归守卫）──
      // waitForResponse 必须在 goto 前挂上：渲染器请求在页面加载后很快发出。
      const tileResponse = page.waitForResponse(
        (res) => res.url().includes("/media/panorama/tiles/"),
        { timeout: 25_000 },
      );
      await page.goto("/#/panorama");
      await expect(page.getByRole("heading", { name: title })).toBeVisible({ timeout: 15_000 });
      await expect(page.locator(".pano-stage")).toBeVisible();
      // 渲染器脚本（自托管 /static/panorama/marzipano.js）必须能加载；
      // 这条与 GPU 无关，能确定性抳住「渲染器资源缺失/改名」这一类退化。
      await page.waitForFunction(() => Boolean((window as any).Marzipano), undefined, {
        timeout: 20_000,
      });

      // 首条取片必须成功：旧病形态是 `…/<uuid>/1//.jpg` 404（{y}/{x} 被替换为空串）。
      const firstTile = await tileResponse;
      expect(firstTile.status(), `查看器首条取片：${firstTile.url()}`).toBe(200);

      // 再给渲染器一点时间把首屏取片发完，然后断言：没有畸形 URL、没有失败响应。
      await page.waitForTimeout(2500);
      const malformed = watched.filter((w) => new URL(w.url).pathname.includes("//"));
      expect(
        malformed,
        `查看器发出畸形取片 URL：${JSON.stringify(malformed.slice(0, 3))}`,
      ).toEqual([]);
      const failedTiles = watched.filter((w) => w.status >= 400);
      expect(failedTiles, `取片失败：${JSON.stringify(failedTiles.slice(0, 3))}`).toEqual([]);
    } catch (err) {
      // 把现场带出 CI（标注可匿名读取，无需仓库日志权限）
      const text = await page.locator("body").innerText().catch(() => "");
      annotateError(
        `panorama e2e failed | url=${page.url()} | watchedTiles=${JSON.stringify(watched.slice(0, 5))} ` +
          `| body=${text.slice(0, 260)} | err=${err instanceof Error ? err.message : String(err)}`,
      );
      throw err;
    }
  });
});
