let audio: AudioContext | null = null;

type Note = readonly [freq: number, at: number];

/** Soft sines made with Web Audio, no audio file: each rises in 10 ms and fades over `decay` seconds. */
function play(list: readonly Note[], peak: number, decay: number): void {
  const AC = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
  if (!AC) return;
  audio ??= new AC();
  void audio.resume();
  const t = audio.currentTime;
  for (const [freq, at] of list) {
    const osc = audio.createOscillator();
    const gain = audio.createGain();
    osc.type = 'sine';
    osc.frequency.value = freq;
    gain.gain.setValueAtTime(0.0001, t + at);
    gain.gain.exponentialRampToValueAtTime(peak, t + at + 0.01);
    gain.gain.exponentialRampToValueAtTime(0.0001, t + at + decay);
    osc.connect(gain).connect(audio.destination);
    osc.start(t + at);
    osc.stop(t + at + decay + 0.05);
  }
}

/** The optional ding (sorting redesign, Moments): two soft sine notes. Every win (phase 17 spec 3.8). */
export function ding(): void {
  play([[880, 0], [1318.5, 0.09]], 0.12, 0.45);
}

/** Phase 17 spec 3.8: the golden acorn's chime, distinct and a little brighter: three rising sines (C6, E6, G6),
 *  quicker and a touch softer, the last one done by 0.5 s. */
export function chime(): void {
  play([[1046.5, 0], [1318.5, 0.06], [1568, 0.12]], 0.1, 0.32);
}
