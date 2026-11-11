"""STT accuracy (plan 15, NFR-2: WER < 12% on Indian-English tech speech) and speed.

Dataset: a folder with manifest.csv (columns: audio,reference) and the audio files (16 kHz mono WAV works best).
Record ~30 minutes of tech answers yourself and transcribe them by hand, or use a licensed Indian-English set
(e.g. AI4Bharat's Svarah; check its license before use).

Usage (from backend/):
    python -m evals.stt_wer path/to/dataset                     # configured STT (models.yaml -> stt)
    python -m evals.stt_wer path/to/dataset --local distil-large-v3 --prompt "FastAPI, LangGraph, pgvector"
"""

import argparse
import asyncio
import csv
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.config import load_models
from app.voice.stt import FILLER_PRIMER, LocalWhisperSTT, SpeechToText, build_stt, wav_duration
from evals.metrics import percentile, word_errors

RESULTS = Path(__file__).parent / "results"
TARGET_WER = 0.12


@dataclass
class FileResult:
    audio: str
    reference: str
    hypothesis: str
    errors: int
    words: int
    seconds: float
    audio_seconds: float | None

    @property
    def wer(self) -> float:
        return self.errors / self.words if self.words else 0.0


def read_manifest(dataset: Path) -> list[dict[str, str]]:
    # utf-8-sig: manifests saved by Excel or PowerShell start with a byte-order mark
    with open(dataset / "manifest.csv", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


async def run(stt: SpeechToText, dataset: Path, prompt: str) -> list[FileResult]:
    rows = read_manifest(dataset)
    out = []
    for row in rows:
        audio = (dataset / row["audio"]).read_bytes()
        start = time.perf_counter()
        t = await stt.transcribe(audio, prompt)
        elapsed = time.perf_counter() - start
        errors, words = word_errors(row["reference"], t.text)
        out.append(FileResult(row["audio"], row["reference"], t.text, errors, words, elapsed, wav_duration(audio)))
    return out


def to_markdown(label: str, results: list[FileResult]) -> str:
    total_err, total_words = sum(r.errors for r in results), sum(r.words for r in results)
    wer = total_err / total_words if total_words else 0.0
    audio_s = sum(r.audio_seconds or 0 for r in results)
    rtf = sum(r.seconds for r in results) / audio_s if audio_s else None
    lat = [r.seconds * 1000 for r in results]
    lines = [
        f"# STT evaluation: {label} ({datetime.now():%Y-%m-%d %H:%M})", "",
        (f"**Corpus WER {wer:.1%}** (target < {TARGET_WER:.0%}) {'✓' if wer < TARGET_WER else '✗'} · "
        f"{len(results)} files · {total_words} reference words · {audio_s / 60:.1f} min of audio"), "",
        f"Latency per file p50 {percentile(lat, 50):.0f} ms / p95 {percentile(lat, 95):.0f} ms"
        + (f" · real-time factor {rtf:.2f}" if rtf else ""), "",
        "| File | WER | Reference | Hypothesis |", "|---|---|---|---|",
    ]
    for r in sorted(results, key=lambda r: -r.wer):
        lines.append(f"| {r.audio} | {r.wer:.0%} | {r.reference[:80]} | {r.hypothesis[:80]} |")
    return "\n".join(lines) + "\n"


async def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("dataset", type=Path)
    p.add_argument("--local", metavar="MODEL", help="use local faster-whisper with this model instead of the config")
    p.add_argument("--prompt", default="", help="extra vocabulary, as the app adds from the candidate's resume")
    args = p.parse_args()

    if args.local:
        stt, label = LocalWhisperSTT(args.local, device="auto", compute_type="int8"), f"faster-whisper {args.local}"
    else:
        cfg = load_models()["stt"]
        stt, label = build_stt(cfg), cfg["model"]
    prompt = f"{FILLER_PRIMER} {args.prompt}".strip()
    results = await run(stt, args.dataset, prompt)
    md = to_markdown(label, results)
    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / f"stt-{datetime.now():%Y%m%d-%H%M%S}.md"
    out.write_text(md, encoding="utf-8")
    print(md)
    print(f"Saved {out}")


if __name__ == "__main__":
    asyncio.run(main())
