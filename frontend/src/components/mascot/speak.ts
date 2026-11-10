/**
 * Speak through the 看板娘 tip bubble without importing the widget chunk.
 * Mirrors live2d-widget's priority gate so idle chatter does not clobber exam lines.
 */

const PRIORITY_KEY = "waifu-message-priority";
const EXAM_PRIORITY = 15;

let hideTimer: number | null = null;
let keepTimer: number | null = null;

export function speakMascot(text: string, durationMs = 5500): void {
  const el = document.getElementById("waifu-tips");
  if (!el || el.hasAttribute("data-mascot-sentinel") || !text) return;

  const current = parseInt(sessionStorage.getItem(PRIORITY_KEY) || "0", 10) || 0;
  if (current > EXAM_PRIORITY) return;

  sessionStorage.setItem(PRIORITY_KEY, String(EXAM_PRIORITY));
  el.innerHTML = text;
  el.classList.add("waifu-tips-active");

  if (hideTimer != null) window.clearTimeout(hideTimer);
  if (keepTimer != null) window.clearInterval(keepTimer);

  keepTimer = window.setInterval(() => {
    el.classList.add("waifu-tips-active");
  }, 400);

  hideTimer = window.setTimeout(() => {
    if (keepTimer != null) window.clearInterval(keepTimer);
    keepTimer = null;
    el.classList.remove("waifu-tips-active");
    if (sessionStorage.getItem(PRIORITY_KEY) === String(EXAM_PRIORITY)) {
      sessionStorage.removeItem(PRIORITY_KEY);
    }
    hideTimer = null;
  }, durationMs);
}
