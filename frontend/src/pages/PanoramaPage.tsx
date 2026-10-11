/**
 * 校园全景图浏览页（`/#/panorama[?id=N]`）。
 *
 * 与旧静态页的差别：不再把 5~8MB 原图整张餵给 WebGL，而是取服务端切好的
 * 多级瓦片（`tile_url_template`）+ `pinFirstLevel` 让最小层常驻打底 ——
 * 首屏只需最小层两张瓦片（百 KB 量级），细节随视野按需补齐。
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import AppShell from "../components/AppShell";
import { api } from "../api/client";
import { panoramaApi } from "../api/panorama";
import {
  PANORAMA_ORIGIN_LABELS,
  PANORAMA_STATUS_LABELS,
  type PanoramaDetail,
  type PanoramaListItem,
} from "../types/panorama";
import { loadMarzipano, preloadImage } from "../utils/marzipano";
import "../styles/panorama.css";

const DEG = Math.PI / 180;

function describe(p: PanoramaListItem): string {
  const bits: string[] = [];
  if (p.width && p.height) bits.push(`${p.width}×${p.height}`);
  if (p.device_model) bits.push(p.device_model);
  bits.push(PANORAMA_ORIGIN_LABELS[p.origin] ?? p.origin);
  return bits.join(" · ");
}

export default function PanoramaPage() {
  const location = useLocation();
  const requestedId = Number(new URLSearchParams(location.search).get("id") || 0);

  const [items, setItems] = useState<PanoramaListItem[] | null>(null);
  const [listError, setListError] = useState("");
  const [current, setCurrent] = useState<PanoramaDetail | null>(null);
  const [sceneLoading, setSceneLoading] = useState(false);
  const [sceneError, setSceneError] = useState("");
  const [canManage, setCanManage] = useState(false);

  const wrapRef = useRef<HTMLDivElement | null>(null);
  const stageRef = useRef<HTMLDivElement | null>(null);
  const viewerRef = useRef<any>(null);

  useEffect(() => {
    document.title = "校园全景 · 传媒社";
  }, []);

  // 公开页：匿名也能看，me() 失败静默（不弹登录）
  useEffect(() => {
    api
      .me()
      .then((d: any) => setCanManage(!!d.user?.permissions?.can_manage_panoramas))
      .catch(() => {});
  }, []);

  useEffect(() => {
    panoramaApi
      .listAll()
      .then((list) => {
        setItems(list);
        setListError("");
      })
      .catch(() => {
        setItems([]);
        setListError("全景图列表加载失败，请稍后重试。");
      });
  }, []);

  // 选中项：URL 上的 id 优先，否则第一张
  const activeId = useMemo(() => {
    if (requestedId && items?.some((p) => p.id === requestedId)) return requestedId;
    return items?.[0]?.id ?? 0;
  }, [items, requestedId]);

  useEffect(() => {
    if (!activeId) {
      setCurrent(null);
      return;
    }
    let alive = true;
    panoramaApi
      .get(activeId)
      .then((detail) => {
        if (alive) setCurrent(detail);
      })
      .catch(() => {
        if (alive) setSceneError("该全景图已不可用。");
      });
    return () => {
      alive = false;
    };
  }, [activeId]);

  // 建场景：切换全景图即重建 viewer（Marzipano 没有公开的「换 source」接口）
  useEffect(() => {
    const stage = stageRef.current;
    if (!current || !stage) return;

    let disposed = false;
    setSceneError("");

    if (!current.tile_url_template || current.tile_levels.length === 0) {
      setSceneError("该全景图尚未切片完成，请稍后重试。");
      setSceneLoading(false);
      return;
    }

    setSceneLoading(true);
    const stageEl = stage;

    (async () => {
      try {
        const Marzipano = await loadMarzipano();
        if (disposed) return;

        // 先等低清预览就绪：它进浏览器缓存后，瓦片请求可以慢慢来
        if (current.preview_url) await preloadImage(current.preview_url);
        if (disposed) return;

        stageEl.innerHTML = "";
        let viewer: any;
        try {
          // 默认 WebGL 舞台：瓦片按需上传纹理，不会撞纹理尺寸上限
          viewer = new Marzipano.Viewer(stageEl);
        } catch {
          // 无 WebGL 的老设备回落到与旧静态页同款的 CSS 舞台
          viewer = new Marzipano.Viewer(stageEl, { stageType: "css" });
        }

        const levels = current.tile_levels.map((l) => ({ width: l.width, tileSize: l.tile_size }));
        const source = Marzipano.ImageUrlSource.fromString(current.tile_url_template);
        const geometry = new Marzipano.EquirectGeometry(levels);
        const limiter = Marzipano.RectilinearView.limit.traditional(current.width, 100 * DEG);
        const view = new Marzipano.RectilinearView(
          {
            yaw: current.initial_yaw * DEG,
            pitch: current.initial_pitch * DEG,
            fov: current.initial_fov * DEG,
          },
          limiter,
        );
        const scene = viewer.createScene({ source, geometry, view, pinFirstLevel: true });

        if (disposed) {
          viewer.destroy();
          return;
        }
        viewerRef.current = viewer;
        scene.switchTo();
        setSceneLoading(false);
      } catch (err: any) {
        if (disposed) return;
        setSceneError(err?.message || "全景图加载失败。");
        setSceneLoading(false);
      }
    })();

    return () => {
      disposed = true;
      try {
        viewerRef.current?.destroy();
      } catch {
        // 销毁失败不影响卸载
      }
      viewerRef.current = null;
    };
  }, [current]);

  const toggleFullscreen = () => {
    const el = wrapRef.current;
    if (!el) return;
    if (document.fullscreenElement) {
      document.exitFullscreen().catch(() => {});
      return;
    }
    if (el.requestFullscreen) el.requestFullscreen().catch(() => {});
  };

  const empty = items !== null && items.length === 0 && !listError;

  return (
    <AppShell>
      <div className="page-head">
        <div className="container">
          <nav className="breadcrumb">
            <Link to="/">主页</Link>
            <span className="sep">/</span>
            <span>校园全景</span>
          </nav>
          <div className="page-head-row">
            <div>
              <h1>{current?.title || "校园全景"}</h1>
              <p className="section-sub">
                {current ? describe(current) : "拖动或滑动即可环视校园。"}
              </p>
            </div>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              <button className="btn btn-ghost" onClick={toggleFullscreen}>全屏</button>
              {canManage && (
                <Link className="btn btn-primary" to="/panorama/manage">管理全景图</Link>
              )}
            </div>
          </div>
        </div>
      </div>

      <div className="container">
        {listError && <p className="pano-note">{listError}</p>}
        {empty && <p className="pano-note">还没有已公开的校园全景图。</p>}

        {current && (
          <div className="pano-stage-wrap" ref={wrapRef}>
            <div className="pano-stage" ref={stageRef} />
            {sceneLoading && !sceneError && <div className="pano-overlay">正在载入全景…</div>}
            {sceneError && <div className="pano-overlay pano-overlay-error">{sceneError}</div>}
            {current.status !== "ready" && (
              <div className="pano-overlay pano-overlay-error">
                该全景图当前状态：{PANORAMA_STATUS_LABELS[current.status] ?? current.status}
              </div>
            )}
          </div>
        )}

        {current && current.description && (
          <p className="pano-desc">{current.description}</p>
        )}

        {items && items.length > 1 && (
          <div className="pano-strip" role="tablist" aria-label="全景图场景">
            {items.map((p) => (
              <Link
                key={p.id}
                to={`/panorama?id=${p.id}`}
                role="tab"
                aria-selected={p.id === activeId}
                className={"pano-chip" + (p.id === activeId ? " active" : "")}
              >
                <span className="pano-chip-art">
                  {p.thumb_url ? <img src={p.thumb_url} alt="" width={800} height={400} loading="lazy" /> : <span className="pano-chip-ph" />}
                </span>
                <span className="pano-chip-text">{p.title}</span>
              </Link>
            ))}
          </div>
        )}
      </div>
    </AppShell>
  );
}
