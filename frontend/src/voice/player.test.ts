import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SentencePlayer } from "./player";

// Minimal stand-ins for the browser audio APIs the player uses
let spoken: string[];
let played: string[];
let finishSpeech: (() => void)[];
let finishAudio: (() => void)[];

class FakeUtterance {
  onend: (() => void) | null = null;
  onerror: (() => void) | null = null;
  lang = "";
  rate = 1;
  voice: unknown = null;
  constructor(public text: string) {}
}

class FakeAudio {
  onended: (() => void) | null = null;
  onerror: (() => void) | null = null;
  constructor(public src: string) {}
  play() {
    played.push(this.src);
    finishAudio.push(() => this.onended?.());
    return Promise.resolve();
  }
  pause() {}
}

beforeEach(() => {
  spoken = [];
  played = [];
  finishSpeech = [];
  finishAudio = [];
  vi.stubGlobal("window", {
    speechSynthesis: {
      getVoices: () => [],
      cancel: () => {},
      speak: (u: FakeUtterance) => {
        spoken.push(u.text);
        finishSpeech.push(() => u.onend?.());
      },
    },
  });
  vi.stubGlobal("SpeechSynthesisUtterance", FakeUtterance);
  vi.stubGlobal("Audio", FakeAudio);
  let n = 0;
  vi.stubGlobal("URL", { createObjectURL: () => `blob:${n++}`, revokeObjectURL: () => {} });
});

afterEach(() => vi.unstubAllGlobals());

describe("SentencePlayer", () => {
  it("speaks browser-mode sentences strictly in order, even if they arrive out of order", () => {
    const speaking: boolean[] = [];
    const p = new SentencePlayer("browser", (s) => speaking.push(s));
    p.addSentence(1, "Second.");
    expect(spoken).toEqual([]); // waits for seq 0
    p.addSentence(0, "First.");
    expect(spoken).toEqual(["First."]);
    finishSpeech.shift()!();
    expect(spoken).toEqual(["First.", "Second."]);
    finishSpeech.shift()!();
    expect(p.busy).toBe(false);
    expect(speaking.at(-1)).toBe(false);
  });

  it("server mode waits for each sentence's audio and falls back to speech when TTS fails", () => {
    const p = new SentencePlayer("server", () => {});
    p.addSentence(0, "Hello.");
    p.addSentence(1, "Question?");
    expect(played).toEqual([]); // no audio yet
    p.addAudio(1, new Blob(["b"]));
    expect(played).toEqual([]); // seq 1's audio can't jump ahead of seq 0
    p.audioFailed(0);
    expect(spoken).toEqual(["Hello."]);
    finishSpeech.shift()!();
    expect(played).toEqual(["blob:0"]);
    finishAudio.shift()!();
    expect(p.busy).toBe(false);
  });

  it("stop() clears the queue", () => {
    const p = new SentencePlayer("browser", () => {});
    p.addSentence(0, "One.");
    p.addSentence(1, "Two.");
    p.stop();
    expect(p.busy).toBe(false);
  });
});
