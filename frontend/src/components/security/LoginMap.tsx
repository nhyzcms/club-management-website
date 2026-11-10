import { useEffect, useRef, useState } from "react";

import type { LoginEventRow } from "../../api/security";

/** 高德 JS API key（可选，webpack DefinePlugin 注入）。没配置时优雅降级为文字位置——不伪造地图。 */
declare const process: { env: Record<string, string | undefined> };
const AMAP_KEY = process.env.AMAP_KEY || "";

export default function LoginMap({ row }: { row: LoginEventRow | null }) {
  const boxRef = useRef<HTMLDivElement>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (!AMAP_KEY || !row || row.latitude == null || row.longitude == null) return;
    let cancelled = false;
    const w = window as any;

    const init = () => {
      if (cancelled || !boxRef.current || !w.AMap) return;
      const map = new w.AMap.Map(boxRef.current, {
        zoom: 6,
        center: [row.longitude, row.latitude],
      });
      new w.AMap.Marker({ position: [row.longitude, row.latitude], map });
    };

    if (w.AMap) {
      init();
      return () => { cancelled = true; };
    }

    const script = document.createElement("script");
    script.src = `https://webapi.amap.com/maps?v=2.0&key=${encodeURIComponent(AMAP_KEY)}`;
    script.async = true;
    script.onload = init;
    script.onerror = () => setFailed(true);
    document.head.appendChild(script);
    return () => { cancelled = true; };
  }, [row]);

  if (!row) return null;

  const place = [row.city, row.region, row.country].filter(Boolean).join(" · ") || "未知位置";
  const hasCoords = row.latitude != null && row.longitude != null;

  if (!AMAP_KEY || failed || !hasCoords) {
    return (
      <div className="sec-map sec-map-fallback">
        <strong>{place}</strong>
        <span className="muted sec-small">
          {!AMAP_KEY
            ? "地图未配置（设置 VITE_AMAP_KEY 后显示地图）"
            : "该位置暂无坐标"}
        </span>
      </div>
    );
  }

  return <div className="sec-map" ref={boxRef} aria-label={`最近登录位置：${place}`} />;
}
