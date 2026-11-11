import { MicVAD, utils } from "@ricky0123/vad-web";
import { useCallback, useEffect, useRef, useState } from "react";
import { interviewSocketUrl } from "../api";
import { SentencePlayer } from "./player";

export type Phase = "connecting" | "speaking" | "listening" | "transcribing" | "thinking" | "ending" | "ended" | "error";
export interface Line {
  speaker: "interviewer" | "candidate";
  text: string;
}

const SAMPLE_RATE = 16000; // Silero VAD delivers 16 kHz mono
// Candidates pause to think mid-answer. VAD ends a speech segment after REDEMPTION_MS of silence;
// the answer is submitted only after SUBMIT_AFTER_MS more without new speech (or when "Done" is clicked).
const REDEMPTION_MS = 600;
const SUBMIT_AFTER_MS = 1200;

export interface InterviewProgress {
  questionNumber: number | null;
  totalQuestions: number | null;
  timeLeftS: number | null;
  receivedAt: number; // ms timestamp, for counting the time down locally
}

/** voice=false: text-only mode, no microphone or VAD. */
export function useVoiceInterview(sessionId: string, voice = true) {
  const [phase, setPhase] = useState<Phase>("connecting");
  const [progress, setProgress] = useState<InterviewProgress>({ questionNumber: null, totalQuestions: null, timeLeftS: null, receivedAt: Date.now() });
  const [lines, setLines] = useState<Line[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [micReady, setMicReady] = useState(false);
  const [candidateSpeaking, setCandidateSpeaking] = useState(false);

  const ws = useRef<WebSocket | null>(null);
  const vad = useRef<MicVAD | null>(null);
  const player = useRef<SentencePlayer | null>(null);
  const segments = useRef<Float32Array[]>([]);
  const submitTimer = useRef<number | undefined>(undefined);
  const pendingAudioSeq = useRef<number | null>(null);
  const turnOpen = useRef(false); // true from turn start until turn_end
  const ended = useRef(false);
  const ending = useRef(false); // End was confirmed: later status messages must not replace "ending"
  const voiceRef = useRef(voice);
  voiceRef.current = voice;

  const appendAi = (text: string) =>
    setLines((ls) => {
      const last = ls[ls.length - 1];
      if (last?.speaker === "interviewer" && turnOpen.current) return [...ls.slice(0, -1), { ...last, text: last.text + text }];
      return [...ls, { speaker: "interviewer", text }];
    });

  // Listen only when no turn is being processed. With the mic on, also wait until the interviewer stops
  // speaking (so the mic never records her); in text mode the candidate can type while she talks.
  const maybeListen = useCallback(() => {
    if (ended.current || turnOpen.current || (voiceRef.current && player.current?.busy)) return;
    setPhase("listening");
    vad.current?.start();
  }, []);

  const submitAudio = useCallback(() => {
    window.clearTimeout(submitTimer.current);
    const parts = segments.current;
    segments.current = [];
    if (!parts.length || ws.current?.readyState !== WebSocket.OPEN) return;
    const merged = new Float32Array(parts.reduce((n, p) => n + p.length, 0));
    let offset = 0;
    for (const p of parts) {
      merged.set(p, offset);
      offset += p.length;
    }
    vad.current?.pause();
    turnOpen.current = true;
    ws.current.send(utils.encodeWAV(merged, 1, SAMPLE_RATE, 1, 16));
    ws.current.send(JSON.stringify({ type: "audio_end" }));
    setPhase("transcribing");
  }, []);

  useEffect(() => {
    let cancelled = false;
    player.current = new SentencePlayer("browser", (speaking) => {
      if (speaking) {
        vad.current?.pause(); // never record the interviewer's own voice
        // In text mode the answer box stays open once the turn is done, even while she's still talking
        if (voiceRef.current || turnOpen.current) setPhase("speaking");
      } else maybeListen();
    });

    const socket = new WebSocket(interviewSocketUrl(sessionId));
    socket.binaryType = "blob";
    ws.current = socket;
    turnOpen.current = true; // the server replays the opening line, then sends turn_end

    socket.onmessage = (ev) => {
      if (ev.data instanceof Blob) {
        if (pendingAudioSeq.current !== null) player.current?.addAudio(pendingAudioSeq.current, ev.data);
        pendingAudioSeq.current = null;
        return;
      }
      const msg = JSON.parse(ev.data);
      if ((msg.type === "ready" || msg.type === "turn_end") && msg.total_questions) {
        setProgress({ questionNumber: msg.question_number, totalQuestions: msg.total_questions, timeLeftS: msg.time_left_s, receivedAt: Date.now() });
      }
      switch (msg.type) {
        case "ready":
          player.current?.setMode(msg.tts);
          break;
        case "status":
          if (!ending.current) setPhase(msg.state);
          break;
        case "transcript_final":
          if (msg.text) setLines((ls) => [...ls, { speaker: "candidate", text: msg.text }]);
          break;
        case "no_speech":
          turnOpen.current = false;
          maybeListen();
          break;
        case "ai_text_delta":
          appendAi(msg.text);
          break;
        case "ai_sentence":
          player.current?.addSentence(msg.seq, msg.text);
          break;
        case "ai_audio":
          pendingAudioSeq.current = msg.seq;
          break;
        case "ai_audio_failed":
          player.current?.audioFailed(msg.seq);
          break;
        case "turn_end":
          turnOpen.current = false;
          if (!msg.done) maybeListen();
          break;
        case "interview_end":
          ended.current = true;
          vad.current?.pause();
          setPhase("ended");
          break;
        case "error":
          setError(msg.message);
          turnOpen.current = false;
          maybeListen();
          break;
      }
    };
    socket.onclose = (ev) => {
      if (ended.current || cancelled) return;
      setPhase("error");
      setError(ev.code === 4401 ? "Your login expired. Please log in again." : ev.code === 4409 ? "This interview is no longer running." : "Connection lost.");
    };

    if (!voice) {
      return () => {
        cancelled = true;
        socket.close();
        player.current?.stop();
      };
    }

    MicVAD.new({
      model: "v5",
      baseAssetPath: "/vad/",
      onnxWASMBasePath: "/vad/",
      startOnLoad: false,
      redemptionMs: REDEMPTION_MS,
      minSpeechMs: 300,
      preSpeechPadMs: 300,
      onSpeechStart: () => {
        window.clearTimeout(submitTimer.current);
        setCandidateSpeaking(true);
      },
      onSpeechEnd: (audio) => {
        setCandidateSpeaking(false);
        segments.current.push(audio);
        submitTimer.current = window.setTimeout(submitAudio, SUBMIT_AFTER_MS);
      },
      onVADMisfire: () => setCandidateSpeaking(false),
    })
      .then((v) => {
        if (cancelled) return v.destroy();
        vad.current = v;
        setMicReady(true);
        maybeListen();
      })
      .catch(() => setError("Microphone unavailable. You can type your answers instead."));

    return () => {
      cancelled = true;
      window.clearTimeout(submitTimer.current);
      socket.close();
      vad.current?.destroy();
      player.current?.stop();
    };
  }, [sessionId, voice, maybeListen, submitAudio]);

  const sendText = useCallback((text: string) => {
    if (!text.trim() || ws.current?.readyState !== WebSocket.OPEN || turnOpen.current) return;
    vad.current?.pause();
    segments.current = [];
    turnOpen.current = true;
    setLines((ls) => [...ls, { speaker: "candidate", text: text.trim() }]);
    ws.current.send(JSON.stringify({ type: "text_answer", text: text.trim() }));
    setPhase("thinking");
  }, []);

  /** Returns false if the request couldn't be sent (connection not open), so the UI can say so. */
  const end = useCallback((): boolean => {
    if (ws.current?.readyState !== WebSocket.OPEN) {
      setError("Not connected to the interview, so it can't be ended from here. Reload the page to reconnect.");
      return false;
    }
    player.current?.stop();
    vad.current?.pause();
    ending.current = turnOpen.current = true;
    setPhase("ending");
    ws.current.send(JSON.stringify({ type: "end_interview" }));
    return true;
  }, []);

  return { phase, lines, error, micReady, candidateSpeaking, progress, sendText, submitNow: submitAudio, end };
}
