import { createRoot } from "react-dom/client";
import "./styles/cobalt.css";
import "./styles/theme-dark.css";
import { initTheme } from "./theme";
import { applyUaSwitch } from "./utils/uaSwitch";
import App from "./App";

// 每次加载（含刷新）都在渲染前检查 UA 类别：移动侧 ↔ 桌面侧变了就直接落到对应版本的
// 页面（详见 utils/uaSwitch.ts）。必须早于 createRoot —— HashRouter 初始化时读的就是
// 这里改过的 hash，因此不会先渲染旧页面再跳。
applyUaSwitch();
initTheme();
createRoot(document.getElementById("root")!).render(<App />);
