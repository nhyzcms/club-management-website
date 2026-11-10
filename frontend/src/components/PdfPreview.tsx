import { useEffect, useRef, useState } from "react";

/**
 * PDF 原件预览（保真排版）：用 pdf.js 把每一页画到 canvas 上。
 *
 * 为什么不用 `<iframe src="...pdf">`：桌面 Chrome 能内嵌 PDF，但 **Android WebView**
 * （我们的 App 壳）与手机 Chrome 不渲染内嵌 PDF，弹窗会变成一片空白。pdf.js 在两端
 * 表现一致，且能按容器宽度等比缩放（手机上不用横向滚动）。
 *
 * 为什么不用 npm 包：pdf.js 的 worker 必须是**独立可 URL 访问的文件**（`new Worker(url)`），
 * cmaps 也要能被内部按需 fetch——这两点都和「打进 bundle」冲突。所以与 Live2D / Marzipano
 * 同样处理：构建产物放在 `frontend/vendor/pdfjs/`，构建时整目录拷到 `/static/pdfjs/`，
 * 运行期再 `<script>` 懒加载（首屏零成本，开源许可见 vendor/pdfjs/LICENSE）。
 *
 * 内存策略（2G 内存的服务器 / 便宜手机）：**每一页只有滚到附近才渲染**
 * （IntersectionObserver + 预取 600px），且总页数封顶 ``MAX_PAGES``。一次性把 40 页
 * A4 画成 canvas 会吃掉几百 MB 显存/内存，长文档直接让低端机崩标签页。
 */
declare global {
  interface Window {
    pdfjsLib?: any;
  }
}

const BASE = "/static/pdfjs";
const SCRIPT_URL = `${BASE}/pdf.min.js`;
const WORKER_URL = `${BASE}/pdf.worker.min.js`;
const CMAP_URL = `${BASE}/cmaps/`;
const MAX_PAGES = 24;
const MAX_CANVAS_WIDTH = 900;
/** canvas 背衬分辨率上限（dpr 取 2 就能看清小字；再高只是白烧内存）。 */
const MAX_DPR = 2;

let pdfjsPromise: Promise<any> | null = null;

function loadPdfjs(): Promise<any> {
  if (window.pdfjsLib) {
    pdfjsPromise = Promise.resolve(window.pdfjsLib);
    return pdfjsPromise;
  }
  if (pdfjsPromise) return pdfjsPromise;

  pdfjsPromise = new Promise((resolve, reject) => {
    const fail = () => {
      pdfjsPromise = null; // 允许下次重试（网络抖动）
      reject(new Error("pdf.js 加载失败"));
    };
    const existing = document.querySelector<HTMLScriptElement>("script[data-pdfjs]");
    const script = existing ?? document.createElement("script");
    script.addEventListener("load", () => {
      const lib = window.pdfjsLib;
      if (!lib) {
        fail();
        return;
      }
      lib.GlobalWorkerOptions.workerSrc = WORKER_URL;
      resolve(lib);
    }, { once: true });
    script.addEventListener("error", fail, { once: true });
    if (!existing) {
      script.src = SCRIPT_URL;
      script.async = true;
      script.dataset.pdfjs = "1";
      document.head.appendChild(script);
    }
  });
  return pdfjsPromise;
}

export default function PdfPreview({ url }: { url: string }) {
  const hostRef = useRef<HTMLDivElement>(null);
  const [renderedPages, setRenderedPages] = useState(0);
  const [note, setNote] = useState("");

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    host.innerHTML = "";
    setRenderedPages(0);
    setNote("");

    let cancelled = false;
    let task: any = null;
    let doc: any = null;
    let observer: IntersectionObserver | null = null;

    const renderPage = async (pageNumber: number, holder: HTMLElement) => {
      if (cancelled || !doc || holder.dataset.rendered === "1") return;
      holder.dataset.rendered = "1";
      const page = await doc.getPage(pageNumber);
      if (cancelled || !host.isConnected) return;
      const base = page.getViewport({ scale: 1 });
      const cssWidth = Math.min(host.clientWidth || 640, MAX_CANVAS_WIDTH);
      const dpr = Math.min(window.devicePixelRatio || 1, MAX_DPR);
      const viewport = page.getViewport({ scale: (cssWidth / base.width) * dpr });
      const canvas = document.createElement("canvas");
      canvas.className = "ann-pdf-page";
      canvas.width = Math.floor(viewport.width);
      canvas.height = Math.floor(viewport.height);
      canvas.setAttribute("role", "img");
      canvas.setAttribute("aria-label", `第 ${pageNumber} 页`);
      const context = canvas.getContext("2d");
      if (!context) throw new Error("canvas context unavailable");
      holder.replaceChildren(canvas);
      await page.render({ canvasContext: context, viewport }).promise;
      if (cancelled) return;
      setRenderedPages((count) => count + 1);
    };

    (async () => {
      try {
        const pdfjs = await loadPdfjs();
        if (cancelled) return;
        task = pdfjs.getDocument({
          url,
          withCredentials: true,        // 原件端点要会话 Cookie（受众鉴权）
          cMapUrl: CMAP_URL,            // 中文 CID 字体编码表（未内嵌 ToUnicode 的 PDF 需要）
          cMapPacked: true,
          isEvalSupported: false,       // 不依赖 eval，日后加 CSP 不会踩坑
        });
        doc = await task.promise;
        if (cancelled || !host.isConnected) return;

        const total = Math.min(doc.numPages, MAX_PAGES);
        const first = await doc.getPage(1);
        const firstBox = first.getViewport({ scale: 1 });
        const ratio = `${firstBox.width} / ${firstBox.height}`; // 占位高度，避免滚动条跳动

        const holders: HTMLElement[] = [];
        for (let n = 1; n <= total; n += 1) {
          const holder = document.createElement("div");
          holder.className = "ann-pdf-holder";
          holder.style.aspectRatio = ratio;
          holder.dataset.page = String(n);
          holder.textContent = `第 ${n} 页`;
          host.appendChild(holder);
          holders.push(holder);
        }

        observer = new IntersectionObserver((entries) => {
          for (const entry of entries) {
            if (!entry.isIntersecting) continue;
            const holder = entry.target as HTMLElement;
            observer?.unobserve(holder);
            void renderPage(Number(holder.dataset.page), holder).catch(() => {
              if (!cancelled) setNote("部分页面渲染失败，请下载原件查看。");
            });
          }
        // root=null（视口）：既照顾弹窗里的内层滚动容器（祖先 overflow 会参与裁剪），
        // 也照顾详情页那种整页滚动的情况。
        }, { root: null, rootMargin: "600px 0px" });
        holders.forEach((holder) => observer?.observe(holder));

        if (doc.numPages > MAX_PAGES) {
          setNote(`文档共 ${doc.numPages} 页，这里只渲染前 ${MAX_PAGES} 页，完整内容请下载原件。`);
        }
      } catch {
        if (!cancelled) setNote("PDF 预览加载失败，请下载原件查看。");
      }
    })();

    return () => {
      cancelled = true;
      observer?.disconnect();
      try { doc?.destroy?.(); } catch { /* 渲染中断时忽略 */ }
      try { task?.destroy?.(); } catch { /* 同上 */ }
    };
  }, [url]);

  return (
    <div className="ann-pdf">
      <div ref={hostRef} className="ann-pdf-host" />
      {note ? (
        <p className="ann-doc-note">{note}</p>
      ) : renderedPages === 0 ? (
        <p className="ann-doc-note">正在渲染 PDF…</p>
      ) : null}
    </div>
  );
}
