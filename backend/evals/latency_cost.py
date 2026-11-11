"""Latency and cost from real sessions (plan 15, NFR-1: p95 turn latency < 2.5 s; NFR-4: < $0.15 per 20 minutes).

Reads llm_calls and turn_timings, which the app fills in during interviews.
Usage (from backend/):  python -m evals.latency_cost [--days 30]
"""

import argparse
import asyncio
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import InterviewSession, LLMCall, TurnTiming
from evals.metrics import percentile

RESULTS = Path(__file__).parent / "results"
TURN_P95_TARGET_MS = 2500
COST_TARGET_PER_20_MIN = 0.15


def _ms(v: float | None) -> str:
    return "n/a" if v is None else f"{v:.0f} ms"


async def build_report(db: AsyncSession, since: datetime) -> str:
    calls = list(await db.scalars(select(LLMCall).where(LLMCall.created_at >= since)))
    timings = list(await db.scalars(select(TurnTiming).where(TurnTiming.created_at >= since)))
    sessions = {s.id: s for s in await db.scalars(select(InterviewSession).where(InterviewSession.created_at >= since))}

    lines = [f"# Latency & cost ({datetime.now():%Y-%m-%d %H:%M}, since {since:%Y-%m-%d})", ""]

    lines += ["## Turn latency (server side, answer received → ...)", ""]
    voice = [t for t in timings if t.mode == "voice"]
    if voice:
        lines += ["| Stage | p50 | p95 |", "|---|---|---|"]
        for label, values in [
            ("STT", [t.stt_ms for t in voice if t.stt_ms is not None]),
            ("First sentence sent", [t.first_sentence_ms for t in voice if t.first_sentence_ms is not None]),
            ("First audio sent (server TTS)", [t.first_audio_ms for t in voice if t.first_audio_ms is not None]),
            ("Turn complete", [t.turn_ms for t in voice]),
        ]:
            lines.append(f"| {label} | {_ms(percentile(values, 50))} | {_ms(percentile(values, 95))} |")
        first = [t.first_audio_ms or t.first_sentence_ms for t in voice if (t.first_audio_ms or t.first_sentence_ms)]
        p95 = percentile(first, 95)
        if p95 is not None:
            # The browser adds VAD end-of-speech wait (redemption + submit delay) and playback start on top
            lines += ["", (f"p95 to first speech: **{p95:.0f} ms** server-side (target < {TURN_P95_TARGET_MS} ms "
                          "end to end, which also includes the client's end-of-speech wait) "
                          f"{'✓' if p95 < TURN_P95_TARGET_MS else '✗'} · {len(voice)} voice turns")]
    else:
        lines.append("_No voice turns recorded yet._")

    lines += ["", "## LLM calls by task", ""]
    by_task: dict[str, list[LLMCall]] = defaultdict(list)
    for c in calls:
        by_task[c.task].append(c)
    if calls:
        lines += ["| Task | Calls | p50 / p95 latency | p50 TTFT | Avg in / out tokens | Fallbacks | JSON invalid | Errors |",
                  "|---|---|---|---|---|---|---|---|"]
        for task, cs in sorted(by_task.items()):
            lat = [c.latency_ms for c in cs]
            ttft = [c.ttft_ms for c in cs if c.ttft_ms is not None]
            fallbacks = sum(c.configured_model is not None and c.model.split("/")[-1] != c.configured_model.split("/")[-1] for c in cs)
            structured = [c for c in cs if c.json_valid is not None]
            invalid = sum(not c.json_valid for c in structured)
            lines.append(
                f"| {task} | {len(cs)} | {_ms(percentile(lat, 50))} / {_ms(percentile(lat, 95))} | {_ms(percentile(ttft, 50))} "
                f"| {sum(c.input_tokens for c in cs) / len(cs):.0f} / {sum(c.output_tokens for c in cs) / len(cs):.0f} "
                f"| {fallbacks / len(cs):.0%} | {f'{invalid / len(structured):.0%}' if structured else '-'} "
                f"| {sum(not c.success and c.json_valid is None for c in cs)} |"
            )
    else:
        lines.append("_No LLM calls recorded yet._")

    lines += ["", "## Cost per interview", ""]
    per_session: dict = defaultdict(float)
    unknown = 0
    for c in calls:
        if c.session_id is None:
            continue
        if c.cost_usd is None:
            unknown += 1
        else:
            per_session[c.session_id] += float(c.cost_usd)
    if per_session:
        # Normalize to 20 minutes so 5- and 30-minute interviews compare against the same target
        per_20 = [cost / max(sessions[sid].duration_s / 1200, 0.25) for sid, cost in per_session.items() if sid in sessions]
        costs = list(per_session.values())
        lines += [
            f"{len(costs)} interviews · mean ${sum(costs) / len(costs):.3f} · p95 ${percentile(costs, 95):.3f} · max ${max(costs):.3f}",
            "",
            (f"Per 20 minutes: mean **${sum(per_20) / len(per_20):.3f}** (target < ${COST_TARGET_PER_20_MIN}) "
            f"{'✓' if per_20 and sum(per_20) / len(per_20) < COST_TARGET_PER_20_MIN else '✗'}"),
        ]
        if unknown:
            lines += ["", f"_{unknown} calls had no known price: add input/output_usd_per_mtok to config/models.yaml._"]
    else:
        lines.append("_No priced calls tied to an interview yet._")
    return "\n".join(lines) + "\n"


async def main() -> None:
    from app.db.session import SessionLocal

    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--days", type=int, default=30)
    args = p.parse_args()
    async with SessionLocal() as db:
        md = await build_report(db, datetime.now(UTC) - timedelta(days=args.days))
    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / f"latency-cost-{datetime.now():%Y%m%d-%H%M%S}.md"
    out.write_text(md, encoding="utf-8")
    print(md)
    print(f"Saved {out}")


if __name__ == "__main__":
    asyncio.run(main())
