/**
 * Classroom cue tones + speech. AudioContext starts on first user gesture.
 */

type CueKind = "errata" | "ending" | "approaching" | "done";

let ctx: AudioContext | null = null;

function audio(): AudioContext | null {
  const Ctor = window.AudioContext || (window as typeof window & { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
  if (!Ctor) return null;
  if (!ctx) ctx = new Ctor();
  if (ctx.state === "suspended") void ctx.resume();
  return ctx;
}

export function unlockExamBoardAudio(): void {
  audio();
}

function beep(at: number, freq: number, dur: number, gain = 0.08): void {
  const ac = audio();
  if (!ac) return;
  const osc = ac.createOscillator();
  const g = ac.createGain();
  osc.type = "sine";
  osc.frequency.value = freq;
  g.gain.setValueAtTime(0.0001, at);
  g.gain.exponentialRampToValueAtTime(gain, at + 0.02);
  g.gain.exponentialRampToValueAtTime(0.0001, at + dur);
  osc.connect(g);
  g.connect(ac.destination);
  osc.start(at);
  osc.stop(at + dur + 0.02);
}

export function playExamCue(kind: CueKind): void {
  const ac = audio();
  if (!ac) return;
  const t = ac.currentTime;
  if (kind === "errata") {
    beep(t, 880, 0.18);
    beep(t + 0.2, 1174, 0.28);
  } else if (kind === "ending") {
    beep(t, 523, 0.12);
    beep(t + 0.16, 523, 0.12);
    beep(t + 0.32, 392, 0.28);
  } else if (kind === "approaching") {
    beep(t, 659, 0.16);
    beep(t + 0.2, 784, 0.22);
  } else {
    beep(t, 349, 0.35, 0.06);
  }
}

export function speakExamVoice(text: string): void {
  const synth = window.speechSynthesis;
  if (!synth || !text) return;
  synth.cancel();
  const u = new SpeechSynthesisUtterance(text);
  u.lang = "zh-CN";
  u.rate = 0.95;
  synth.speak(u);
}
