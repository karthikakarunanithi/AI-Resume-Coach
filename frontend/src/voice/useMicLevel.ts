import { useEffect, useState } from "react";

/** Live microphone level 0..1 while `enabled` (mic check, listening indicator). */
export function useMicLevel(enabled: boolean): { level: number; error: string | null } {
  const [level, setLevel] = useState(0);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!enabled) {
      setLevel(0);
      return;
    }
    let raf = 0;
    let stream: MediaStream | null = null;
    let ctx: AudioContext | null = null;
    let stopped = false;

    navigator.mediaDevices
      ?.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } })
      .then((s) => {
        if (stopped) return s.getTracks().forEach((t) => t.stop());
        stream = s;
        ctx = new AudioContext();
        const analyser = ctx.createAnalyser();
        analyser.fftSize = 512;
        ctx.createMediaStreamSource(s).connect(analyser);
        const buf = new Float32Array(analyser.fftSize);
        const tick = () => {
          analyser.getFloatTimeDomainData(buf);
          let sum = 0;
          for (const v of buf) sum += v * v;
          const rms = Math.sqrt(sum / buf.length);
          setLevel(Math.min(1, rms * 6)); // normal speech lands around 0.3-0.8
          raf = requestAnimationFrame(tick);
        };
        tick();
        setError(null);
      })
      .catch(() => setError("Microphone blocked or not found. Allow access in your browser, or answer by typing."));

    if (!navigator.mediaDevices) setError("This browser can't use a microphone here (it needs https or localhost).");

    return () => {
      stopped = true;
      cancelAnimationFrame(raf);
      stream?.getTracks().forEach((t) => t.stop());
      ctx?.close();
    };
  }, [enabled]);

  return { level, error };
}
