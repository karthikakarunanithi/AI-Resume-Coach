"""Evaluator quality (plan 15): agreement with human ratings, consistency, robustness, latency and cost per model.

Usage (from backend/, API keys in ../.env):
    python -m evals.run_evaluator                                    # configured evaluator model, 5 runs
    python -m evals.run_evaluator --models anthropic/claude-sonnet-5-5,anthropic/claude-haiku-5-5 --runs 3
    python -m evals.run_evaluator --only robustness                  # the 13 robustness cases only
    python -m evals.run_evaluator --concurrency 1                    # free tiers: stay under per-minute token caps

Writes evals/results/evaluator-<timestamp>.md and .json.
"""

import argparse
import asyncio
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from app.config import load_models, load_rubric
from app.llm.client import LLMClient
from app.llm.errors import describe
from app.llm.schemas import AnswerEvaluation
from app.llm.usage import LLMCallRecord
from app.services.evaluator import evaluate_answer
from evals.dataset import ANSWERS, ROBUSTNESS, EvalCase, load_cases
from evals.metrics import mae, percentile, spearman, stdev

RESULTS = Path(__file__).parent / "results"
TARGETS = {"spearman": 0.7, "mae": 0.7, "std": 0.3}


@dataclass
class CaseResult:
    case_id: str
    overalls: list[float]
    scores: list[dict[str, int]]
    errors: int = 0
    error_messages: list[str] = field(default_factory=list)

    @property
    def mean_overall(self) -> float | None:
        return sum(self.overalls) / len(self.overalls) if self.overalls else None


@dataclass
class ModelReport:
    model: str
    runs: int
    cases: int
    agreement_n: int = 0
    spearman: float | None = None
    mae: float | None = None
    dimension_mae: dict[str, float] = field(default_factory=dict)
    human_spearman: float | None = None  # rater A vs rater B: the ceiling for any evaluator
    mean_std: float | None = None
    max_std: float | None = None
    robustness: list[dict] = field(default_factory=list)
    latency_p50_ms: float | None = None
    latency_p95_ms: float | None = None
    cost_per_eval_usd: float | None = None
    json_failure_rate: float | None = None
    errors: int = 0
    error_examples: list[str] = field(default_factory=list)


async def run_model(
    model: str, cases: list[EvalCase], runs: int, llm: LLMClient | None = None, concurrency: int = 4
) -> tuple[ModelReport, list[CaseResult]]:
    records: list[LLMCallRecord] = []
    if llm is None:
        models = load_models()
        cfg = {**models["evaluator"], "model": model, "fallbacks": []}  # measure this model, not its fallback
        if model != models["evaluator"]["model"]:
            # models.yaml prices belong to the configured model; others use LiteLLM's price table
            cfg = {k: v for k, v in cfg.items() if k not in ("input_usd_per_mtok", "output_usd_per_mtok")}
        llm = LLMClient({**models, "evaluator": cfg}, recorder=records.append)
    elif llm.recorder is None:
        llm.recorder = records.append

    sem = asyncio.Semaphore(concurrency)
    results = {c.id: CaseResult(c.id, [], []) for c in cases}

    async def one(case: EvalCase) -> None:
        async with sem:
            try:
                ev: AnswerEvaluation = await evaluate_answer(
                    llm, case.question_dict(), case.turns(), case.interview_type
                )
            except Exception as e:  # noqa: BLE001 - a failed call is counted and reported, not fatal
                results[case.id].errors += 1
                results[case.id].error_messages.append(describe(e, 160))
                return
            results[case.id].overalls.append(ev.overall)
            results[case.id].scores.append(ev.scores)

    await asyncio.gather(*(one(c) for c in cases for _ in range(runs)))
    report = summarize(model, cases, list(results.values()), runs, records)
    return report, list(results.values())


def summarize(
    model: str, cases: list[EvalCase], results: list[CaseResult], runs: int, records: list[LLMCallRecord]
) -> ModelReport:
    by_id = {r.case_id: r for r in results}
    rep = ModelReport(model=model, runs=runs, cases=len(cases), errors=sum(r.errors for r in results),
                      error_examples=sorted({m for r in results for m in r.error_messages})[:5])

    # Agreement with humans on rated cases
    rated = [c for c in cases if c.ratings and by_id[c.id].overalls]
    rep.agreement_n = len(rated)
    if rated:
        human = [c.human_mean_overall() for c in rated]
        model_scores = [by_id[c.id].mean_overall for c in rated]
        rep.spearman, rep.mae = spearman(human, model_scores), mae(human, model_scores)
        dims = load_rubric()
        per_dim: dict[str, list[float]] = {}
        for c in rated:
            for d in dims[c.interview_type]:
                h = sum(r[d] for r in c.ratings.values()) / len(c.ratings)
                m = sum(s[d] for s in by_id[c.id].scores) / len(by_id[c.id].scores)
                per_dim.setdefault(d, []).append(abs(h - m))
        rep.dimension_mae = {d: round(sum(v) / len(v), 2) for d, v in per_dim.items()}
        two_raters = [c for c in rated if len(c.ratings) >= 2]
        if len(two_raters) >= 3:
            a, b = (sorted(two_raters[0].ratings)[i] for i in (0, 1))
            pairs = [(c.human_overall(a), c.human_overall(b)) for c in two_raters if a in c.ratings and b in c.ratings]
            rep.human_spearman = spearman([p[0] for p in pairs], [p[1] for p in pairs])

    # Consistency across repeated runs of the same case
    stds = [stdev(r.overalls) for r in results if len(r.overalls) >= 2]
    if stds:
        rep.mean_std, rep.max_std = sum(stds) / len(stds), max(stds)

    # Robustness expectations
    for c in cases:
        if c.expect is None or not by_id[c.id].overalls:
            continue
        r = by_id[c.id]
        overall, failures = r.mean_overall, []
        e = c.expect
        if e.max_overall is not None and overall > e.max_overall:
            failures.append(f"overall {overall:.2f} > {e.max_overall}")
        if e.min_overall is not None and overall < e.min_overall:
            failures.append(f"overall {overall:.2f} < {e.min_overall}")
        for d, cap in e.max_scores.items():
            worst = max(s.get(d, 0) for s in r.scores)
            if worst > cap:
                failures.append(f"{d} {worst} > {cap}")
        if e.same_as and by_id.get(e.same_as) and by_id[e.same_as].overalls:
            other = by_id[e.same_as].mean_overall
            if abs(overall - other) > e.tolerance:
                failures.append(f"overall {overall:.2f} vs {e.same_as} {other:.2f} (tolerance {e.tolerance})")
        rep.robustness.append({"case": c.id, "overall": round(overall, 2), "passed": not failures, "why": "; ".join(failures)})

    # Latency, cost, structured-output failures
    ok = [r for r in records if r.task == "evaluator"]
    if ok:
        lat = [r.latency_ms for r in ok]
        rep.latency_p50_ms, rep.latency_p95_ms = percentile(lat, 50), percentile(lat, 95)
        costs = [r.cost_usd for r in ok if r.cost_usd is not None]
        evaluations = sum(len(r.overalls) for r in results) or 1
        rep.cost_per_eval_usd = sum(costs) / evaluations if costs else None
        structured = [r for r in ok if r.json_valid is not None]
        rep.json_failure_rate = sum(not r.json_valid for r in structured) / len(structured) if structured else None
    return rep


def _fmt(v, spec=".2f", none="n/a"):
    return none if v is None else format(v, spec)


def _mark(value, target, higher_is_better=True):
    if value is None:
        return ""
    ok = value >= target if higher_is_better else value <= target
    return " ✓" if ok else " ✗"


def to_markdown(reports: list[ModelReport]) -> str:
    lines = [
        f"# Evaluator evaluation ({datetime.now():%Y-%m-%d %H:%M})", "",
        (f"Targets: Spearman ρ ≥ {TARGETS['spearman']}, MAE ≤ {TARGETS['mae']} (1-5 scale), "
        f"score std across runs ≤ {TARGETS['std']}, all robustness cases pass."), "",
        "| Model | Rated cases | Spearman ρ | MAE | Human-human ρ | Mean std | Robustness | p50 / p95 latency | Cost / eval | JSON failures |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in reports:
        passed = sum(x["passed"] for x in r.robustness)
        lines.append(
            f"| `{r.model}` | {r.agreement_n} | {_fmt(r.spearman)}{_mark(r.spearman, TARGETS['spearman'])} "
            f"| {_fmt(r.mae)}{_mark(r.mae, TARGETS['mae'], False)} | {_fmt(r.human_spearman)} "
            f"| {_fmt(r.mean_std)}{_mark(r.mean_std, TARGETS['std'], False)} | {passed}/{len(r.robustness)} "
            f"| {_fmt(r.latency_p50_ms, '.0f')} / {_fmt(r.latency_p95_ms, '.0f')} ms "
            f"| {_fmt(r.cost_per_eval_usd, '.4f', 'unknown price')} | {_fmt(r.json_failure_rate, '.0%')} |"
        )
    for r in reports:
        if r.dimension_mae:
            lines += ["", f"**{r.model}**: MAE per dimension: " + ", ".join(f"{d} {v}" for d, v in r.dimension_mae.items())]
        failed = [x for x in r.robustness if not x["passed"]]
        if failed:
            lines += ["", f"**{r.model}**: failed robustness cases:"] + [f"- `{x['case']}`: {x['why']}" for x in failed]
        if r.errors:
            lines += ["", f"**{r.model}**: {r.errors} evaluation calls errored:"] + [f"- {m}" for m in r.error_examples]
    if any(r.agreement_n == 0 for r in reports):
        lines += ["", ("_No human-rated cases yet: export answers (`python -m evals.export_answers`) and rate them "
                      "(`python -m evals.rate --rater <name>`) to measure agreement._")]
    return "\n".join(lines) + "\n"


async def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--models", default=load_models()["evaluator"]["model"])
    p.add_argument("--runs", type=int, default=5)
    p.add_argument("--only", choices=["robustness", "rated"])
    p.add_argument("--concurrency", type=int, default=4)
    args = p.parse_args()

    cases = load_cases(ROBUSTNESS) + load_cases(ANSWERS)
    if args.only == "robustness":
        cases = [c for c in cases if c.source == "robustness"]
    elif args.only == "rated":
        cases = [c for c in cases if c.ratings]
    print(f"{len(cases)} cases ({sum(bool(c.ratings) for c in cases)} human-rated) x {args.runs} runs")

    reports = []
    for model in args.models.split(","):
        print(f"Evaluating with {model} ...")
        report, results = await run_model(model.strip(), cases, args.runs, concurrency=args.concurrency)
        reports.append((report, results))

    md = to_markdown([r for r, _ in reports])
    RESULTS.mkdir(exist_ok=True)
    stem = RESULTS / f"evaluator-{datetime.now():%Y%m%d-%H%M%S}"
    stem.with_suffix(".md").write_text(md, encoding="utf-8")
    stem.with_suffix(".json").write_text(json.dumps(
        [{"report": asdict(r), "cases": [asdict(c) for c in res]} for r, res in reports], indent=2
    ), encoding="utf-8")
    print(md)
    print(f"Saved {stem}.md")


if __name__ == "__main__":
    asyncio.run(main())
