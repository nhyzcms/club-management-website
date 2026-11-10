const KEY = "examBoardPrefs";
const VERSION = 3;

export type ExamBoardPrefs = {
  mascot: boolean;
  sound: boolean;
  voice: boolean;
};

const DEFAULTS: ExamBoardPrefs = { mascot: false, sound: false, voice: false };

export function loadExamBoardPrefs(): ExamBoardPrefs {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return { ...DEFAULTS };
    const parsed = JSON.parse(raw);
    // v2 及更早的记录里 mascot / sound 的默认值就是开的，分不清「用户主动开启」
    // 和「默认值」，所以 v3 起把旧记录统一按「未选择」处理，一次性落成关闭。
    if (parsed?.v !== VERSION) return { ...DEFAULTS };
    return {
      mascot: parsed.mascot === true,
      sound: parsed.sound === true,
      voice: parsed.voice === true,
    };
  } catch {
    return { ...DEFAULTS };
  }
}

export function saveExamBoardPrefs(prefs: ExamBoardPrefs): void {
  localStorage.setItem(KEY, JSON.stringify({ v: VERSION, ...prefs }));
  window.dispatchEvent(new CustomEvent("exam-board-prefs"));
}

export function applyExamBoardMascotClass(show: boolean): void {
  document.body.classList.toggle("exam-board-hide-mascot", !show);
}
