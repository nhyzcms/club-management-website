import { useEffect, useLayoutEffect, useState } from "react";
import { applyExamBoardMascotClass, loadExamBoardPrefs, saveExamBoardPrefs } from "../../examBoard/prefs";
import "./mascot.css";

const STORAGE_KEY = "mascot.enabled";
const NARROW_MAX = 1024;
const REDUCE_MOTION_QUERY = "(prefers-reduced-motion: reduce)";

type Presentation = "none" | "chip" | "widget";

function readEnabled(): boolean {
  return localStorage.getItem(STORAGE_KEY) !== "off";
}

function writeEnabled(on: boolean): void {
  localStorage.setItem(STORAGE_KEY, on ? "on" : "off");
}

function onExamBoard(): boolean {
  return document.body.classList.contains("exam-board-on");
}

function computePresentation(): Presentation {
  if (onExamBoard()) {
    return loadExamBoardPrefs().mascot ? "widget" : "none";
  }
  if (window.innerWidth <= NARROW_MAX) return "none";
  if (window.matchMedia(REDUCE_MOTION_QUERY).matches) return "none";
  return readEnabled() ? "widget" : "chip";
}

/**
 * Site-wide 看板娘 host. App.tsx learns only `<MascotHost />`.
 * Three presentations (widget / chip / none); Cubism is lazy and never
 * remounts on hash changes because this host sits outside <Routes>.
 * On 考试看板 the page's own 「显示看板娘」 pref mounts/unmounts the widget.
 */
export default function MascotHost() {
  const [presentation, setPresentation] = useState<Presentation>(computePresentation);

  useLayoutEffect(() => {
    const motionMq = window.matchMedia(REDUCE_MOTION_QUERY);
    const narrowMq = window.matchMedia(`(max-width: ${NARROW_MAX}px)`);
    const sync = () => setPresentation(computePresentation());
    window.addEventListener("resize", sync);
    window.addEventListener("exam-board-prefs", sync);
    motionMq.addEventListener("change", sync);
    narrowMq.addEventListener("change", sync);
    window.visualViewport?.addEventListener("resize", sync);
    const obs = new MutationObserver(sync);
    obs.observe(document.body, { attributes: true, attributeFilter: ["class"] });
    sync();
    return () => {
      window.removeEventListener("resize", sync);
      window.removeEventListener("exam-board-prefs", sync);
      motionMq.removeEventListener("change", sync);
      narrowMq.removeEventListener("change", sync);
      window.visualViewport?.removeEventListener("resize", sync);
      obs.disconnect();
    };
  }, []);

  useEffect(() => {
    if (presentation !== "widget") return;
    let cancelled = false;
    let unmount: (() => void) | undefined;

    import(/* webpackChunkName: "mascot-widget" */ "./loadWidget")
      .then((mod) => {
        if (cancelled) return undefined;
        return mod.mountMascotWidget({
          onClose: () => {
            writeEnabled(false);
            if (onExamBoard()) {
              saveExamBoardPrefs({ ...loadExamBoardPrefs(), mascot: false });
              applyExamBoardMascotClass(false);
              setPresentation("none");
              return;
            }
            setPresentation("chip");
          },
        });
      })
      .then((handle) => {
        if (!handle) return;
        if (cancelled) {
          handle.unmount();
          return;
        }
        unmount = handle.unmount;
      })
      .catch(() => undefined);

    return () => {
      cancelled = true;
      unmount?.();
    };
  }, [presentation]);

  if (presentation !== "chip") return null;

  return (
    <button
      type="button"
      className="mascot-chip"
      aria-label="看板娘"
      onClick={() => {
        writeEnabled(true);
        setPresentation("widget");
      }}
    >
      看板娘
    </button>
  );
}
