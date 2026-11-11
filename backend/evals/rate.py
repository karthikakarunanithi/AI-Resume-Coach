"""Blind human rating of exported answers with the same rubric the evaluator uses (plan 15: 2 raters).

Usage (from backend/):  python -m evals.rate --rater alice

Shows each unrated answer (in a fixed shuffled order per rater, without the model's scores) and asks for a
1-5 score per rubric dimension. Ratings are saved after every answer, so you can stop and resume anytime.
"""

import argparse
import random
from collections.abc import Callable

from app.config import load_rubric
from evals.dataset import ANSWERS, EvalCase, load_cases, save_cases

SCALE = "1 = missing or wrong, 2 = weak, 3 = acceptable, 4 = strong, 5 = excellent"


def render_case(case: EvalCase, rubric: dict) -> str:
    lines = [f"QUESTION ({case.interview_type}): {case.question}", "", "Ideal key points:"]
    lines += [f"  - {p}" for p in case.ideal_key_points]
    lines += ["", "Transcript:"]
    lines += [f"  {'Interviewer' if t.speaker == 'interviewer' else 'Candidate'}: {t.text}" for t in case.transcript]
    lines += ["", f"Rubric ({SCALE}):"]
    lines += [f"  {d}: {spec['description']}" for d, spec in rubric.items()]
    return "\n".join(lines)


def ask_scores(rubric: dict, ask: Callable[[str], str]) -> dict[str, int] | None:
    """Prompt for each dimension; returns None if the rater types 's' (skip) or 'q' (quit is raised)."""
    scores: dict[str, int] = {}
    for dim in rubric:
        while True:
            raw = ask(f"  {dim} [1-5, s=skip, q=quit]: ").strip().lower()
            if raw == "q":
                raise KeyboardInterrupt
            if raw == "s":
                return None
            if raw in {"1", "2", "3", "4", "5"}:
                scores[dim] = int(raw)
                break
    return scores


def rate(cases: list[EvalCase], rater: str, ask: Callable[[str], str], show: Callable[[str], None], save) -> int:
    rubrics = load_rubric()
    todo = [c for c in cases if rater not in c.ratings]
    random.Random(rater).shuffle(todo)  # each rater sees their own fixed order: less order bias, resumable
    done = 0
    for i, case in enumerate(todo, 1):
        show(f"\n{'=' * 80}\n[{i}/{len(todo)}]\n{render_case(case, rubrics[case.interview_type])}\n")
        scores = ask_scores(rubrics[case.interview_type], ask)
        if scores is None:
            continue
        case.ratings[rater] = scores
        save(cases)
        done += 1
    return done


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--rater", required=True, help="your name; each rater rates independently")
    args = p.parse_args()

    cases = load_cases(ANSWERS)
    if not cases:
        print(f"No answers in {ANSWERS}. Run `python -m evals.export_answers` first.")
        return
    try:
        n = rate(cases, args.rater, input, print, lambda cs: save_cases(ANSWERS, cs))
    except KeyboardInterrupt:
        n = None
    rated = sum(args.rater in c.ratings for c in cases)
    print(f"\nSaved. {args.rater} has rated {rated}/{len(cases)} answers" + (f" ({n} this session)." if n is not None else "."))


if __name__ == "__main__":
    main()
