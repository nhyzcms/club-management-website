import { useTheme } from "../theme";
import "./ThemeToggle.css";

/** 4 角闪光星形路径（与 WPF 参考实现同源的星形几何）。 */
const SPARKLE_PATH =
  "M100,50 C72.38589,50 50,72.38589 50,100 C50,72.38589 27.61411,50 0,50 C27.61411,50 50,27.61411 50,0 C50,27.61411 72.38589,50 100,50 Z";

/** 星星位置与大小（220×90 基准坐标系）。 */
const SPARKLES = [
  { x: 32, y: 16, size: 16 },
  { x: 68, y: 54, size: 10 },
  { x: 97, y: 30, size: 13 },
  { x: 52, y: 68, size: 9 },
  { x: 14, y: 58, size: 8 },
];

/**
 * 昼夜切换开关（顶栏 / 手机版顶栏）。
 *
 * 复刻 jh3y《Night && Day Toggle ☀️/🌙》的经典拟物开关（参照 chokcoco 的
 * 「单标签」CSS 版）：凸面外框、太阳⇄月亮滑动、云朵淡出、星空亮起、
 * 天空由昼转夜。纯 CSS 绘制，无图片素材、无新依赖。
 *
 * 点击在浅色/深色之间显式切换；「跟随系统」仍可在外观菜单里选择。
 */
export default function ThemeToggle() {
  const { resolved, setPref } = useTheme();
  const dark = resolved === "dark";

  return (
    <button
      type="button"
      role="switch"
      aria-checked={dark}
      aria-label="深色模式"
      className="dn-switch"
      onClick={() => setPref(dark ? "light" : "dark")}
    >
      <span className="dn-box" aria-hidden="true">
        <span className="dn-glow" />
        <span className="dn-clouds" />
        <span className="dn-sparkles">
          {SPARKLES.map((s, i) => (
            <svg key={i} viewBox="0 0 100 100" width={s.size} height={s.size} style={{ left: s.x, top: s.y }}>
              <path d={SPARKLE_PATH} />
            </svg>
          ))}
        </span>
        <span className="dn-disc" />
      </span>
    </button>
  );
}
