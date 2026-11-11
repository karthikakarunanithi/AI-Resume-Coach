/**
 * Plays the interviewer's sentences strictly in order (by seq).
 * - "browser" TTS mode: speaks each sentence's text with speechSynthesis.
 * - "server" mode: waits for that sentence's audio; if the server reports a TTS failure, speaks the text instead.
 */
type Item = { text: string; audio?: Blob; failed?: boolean };

export class SentencePlayer {
  private items = new Map<number, Item>();
  private next = 0;
  private playing = false;
  private current: HTMLAudioElement | null = null;

  constructor(
    private mode: "browser" | "server",
    private onSpeakingChange: (speaking: boolean) => void,
  ) {}

  setMode(mode: "browser" | "server") {
    this.mode = mode;
  }

  addSentence(seq: number, text: string) {
    this.items.set(seq, { ...this.items.get(seq), text });
    this.pump();
  }

  addAudio(seq: number, audio: Blob) {
    const item = this.items.get(seq);
    if (item) {
      item.audio = audio;
      this.pump();
    }
  }

  audioFailed(seq: number) {
    const item = this.items.get(seq);
    if (item) {
      item.failed = true;
      this.pump();
    }
  }

  get busy(): boolean {
    return this.playing || this.items.has(this.next);
  }

  stop() {
    this.items.clear();
    this.current?.pause();
    window.speechSynthesis?.cancel();
    this.playing = false;
    this.onSpeakingChange(false);
  }

  private pump() {
    if (this.playing) return;
    const item = this.items.get(this.next);
    if (!item) {
      this.onSpeakingChange(false);
      return;
    }
    const useAudio = this.mode === "server" && item.audio;
    const useVoice = this.mode === "browser" || item.failed;
    if (!useAudio && !useVoice) return; // server audio for this sentence hasn't arrived yet

    this.playing = true;
    this.onSpeakingChange(true);
    const done = () => {
      this.items.delete(this.next);
      this.next += 1;
      this.playing = false;
      this.current = null;
      this.pump();
    };
    if (useAudio) {
      const url = URL.createObjectURL(item.audio!);
      this.current = new Audio(url);
      this.current.onended = this.current.onerror = () => {
        URL.revokeObjectURL(url);
        done();
      };
      this.current.play().catch(done);
    } else {
      speakWithBrowser(item.text, done);
    }
  }
}

function speakWithBrowser(text: string, onDone: () => void) {
  const synth = window.speechSynthesis;
  if (!synth) {
    onDone();
    return;
  }
  const u = new SpeechSynthesisUtterance(text);
  u.lang = "en-US";
  u.rate = 1.0;
  const voice = synth.getVoices().find((v) => v.lang.startsWith("en") && /female|zira|samantha|aria|jenny/i.test(v.name));
  if (voice) u.voice = voice;
  u.onend = u.onerror = () => onDone();
  synth.speak(u);
}
