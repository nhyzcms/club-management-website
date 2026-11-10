import { useEffect, useRef } from "react";

interface Props {
  className?: string;
  /** 粒子密度系数，越大越稀疏（默认 70，约每 63 万 px² 一颗） */
  density?: number;
}

const COLORS = ["#3da5f3", "#79c2fa", "#00e5ff", "#7b5cff", "#ff2d95"];

interface Pt {
  x: number;
  y: number;
  r: number;
  vx: number;
  vy: number;
  c: string;
  a: number;
  tw: number;
}

/**
 * 轻量霓虹粒子背景（零依赖 canvas）。
 * 漂浮光点 + 柔和光晕，随滚动/尺寸自适应；prefers-reduced-motion 时静默跳过。
 */
export default function NeonParticles({ className = "", density = 70 }: Props) {
  const ref = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let w = 0;
    let h = 0;
    let raf = 0;
    let pts: Pt[] = [];

    const make = (): Pt => ({
      x: Math.random() * w,
      y: Math.random() * h,
      r: 0.6 + Math.random() * 1.7,
      vx: (Math.random() - 0.5) * 0.14,
      vy: -0.04 - Math.random() * 0.26,
      c: COLORS[(Math.random() * COLORS.length) | 0],
      a: 0.16 + Math.random() * 0.5,
      tw: 0.5 + Math.random() * 2.6,
    });

    const resize = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      w = canvas.clientWidth;
      h = canvas.clientHeight;
      if (w < 8 || h < 8) return;
      canvas.width = Math.round(w * dpr);
      canvas.height = Math.round(h * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      const n = Math.max(12, Math.round((w * h) / (density * 9000)));
      pts = Array.from({ length: n }, make);
    };

    const tick = (t: number) => {
      ctx.clearRect(0, 0, w, h);
      for (const p of pts) {
        p.x += p.vx;
        p.y += p.vy;
        if (p.y < -10) {
          p.y = h + 10;
          p.x = Math.random() * w;
        }
        if (p.x < -10) p.x = w + 10;
        if (p.x > w + 10) p.x = -10;
        const alpha = p.a * (0.55 + 0.45 * Math.sin((t / 1000) * p.tw + p.x * 0.05));
        ctx.globalAlpha = alpha;
        ctx.fillStyle = p.c;
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
        ctx.fill();
        ctx.globalAlpha = alpha * 0.22;
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.r * 3.4, 0, Math.PI * 2);
        ctx.fill();
      }
      ctx.globalAlpha = 1;
      raf = requestAnimationFrame(tick);
    };

    resize();
    raf = requestAnimationFrame(tick);
    window.addEventListener("resize", resize);
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", resize);
    };
  }, [density]);

  return <canvas ref={ref} className={className} aria-hidden="true" />;
}
