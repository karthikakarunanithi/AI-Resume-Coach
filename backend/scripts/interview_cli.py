"""Text-mode mock interview in the terminal (week 3 milestone).

Usage (from backend/, with API keys in ../.env):
    python -m scripts.interview_cli --resume path/to/resume.pdf --role "GenAI Developer"
    python -m scripts.interview_cli --resume cv.docx --jd jd.txt --type behavioral --minutes 20 --difficulty hard
    python -m scripts.interview_cli --role "ML Engineer" --no-bank      # no Postgres needed

Type your answer and press Enter. "/end" ends the interview early.
At the end the scored report is printed and saved as JSON (--report-out).
"""

import argparse
import asyncio
import logging
import textwrap
from pathlib import Path

from langgraph.checkpoint.memory import InMemorySaver

from app.agents.graph import build_interview_graph
from app.agents.runner import InterviewRunner, TurnResult
from app.llm.client import LLMClient
from app.services.evaluator import BackgroundEvaluator
from app.services.parsers import analyze_jd, parse_resume
from app.services.report import FinalReport, build_report
from app.services.text_extract import extract_text


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--resume", type=Path, help="PDF or DOCX resume")
    p.add_argument("--jd", type=Path, help="job description as a text file")
    p.add_argument("--role", default="AI Engineer")
    p.add_argument("--type", default="technical", choices=["technical", "behavioral", "hr", "system_design"])
    p.add_argument("--difficulty", default="medium", choices=["easy", "medium", "hard"])
    p.add_argument("--minutes", type=int, default=10)
    p.add_argument("--company-type", default="product company")
    p.add_argument("--no-bank", action="store_true", help="skip question-bank retrieval (no database needed)")
    p.add_argument("--report-out", type=Path, default=Path("interview_report.json"))
    p.add_argument("--verbose", action="store_true")
    return p.parse_args()


def say(result: TurnResult) -> None:
    for line in result.spoken:
        print("\n" + textwrap.fill(f"Asha: {line}", width=100, subsequent_indent="      "))


async def main() -> None:
    args = parse_args()
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING)
    llm = LLMClient()

    profile, jd = {}, None
    if args.resume:
        print("Parsing resume...")
        profile = (await parse_resume(llm, extract_text(args.resume.read_bytes()))).model_dump()
    if args.jd:
        print("Analyzing job description...")
        jd = (await analyze_jd(llm, args.jd.read_text(encoding="utf-8"))).model_dump()

    retriever, db = None, None
    if not args.no_bank:
        from app.db.session import SessionLocal
        from app.rag.embeddings import get_embedder
        from app.rag.retriever import HybridRetriever

        db = SessionLocal()
        retriever = HybridRetriever(db, get_embedder())

    graph = build_interview_graph(llm, retriever=retriever, checkpointer=InMemorySaver())
    runner = InterviewRunner(graph, evaluator=BackgroundEvaluator(llm, args.type))
    print(f"Planning a {args.minutes}-minute {args.type} interview for {args.role}...")
    try:
        result = await runner.start(
            {"role": args.role, "interview_type": args.type, "difficulty": args.difficulty,
             "duration_min": args.minutes, "company_type": args.company_type},
            profile, jd,
        )
        say(result)
        while not result.done:
            answer = await asyncio.to_thread(input, "\nYou: ")
            if answer.strip() == "/end":
                result = await runner.answer("", end=True)
            else:
                result = await runner.answer(answer)
            say(result)
    finally:
        if db is not None:
            await db.close()

    print("\nScoring your answers...")
    report = await build_report(llm, await runner.state(), await runner.evaluations())
    args.report_out.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    print_report(report)
    print(f"\nFull report saved to {args.report_out}")


def print_report(r: FinalReport) -> None:
    print(f"\n=== {r.overall_score}/100 ({r.hiring_signal}), {r.questions_answered}/{r.questions_planned} questions ===")
    print(textwrap.fill(r.summary, width=100))
    for title, items in (("Strengths", r.strengths), ("Improve", r.improvements)):
        print(f"\n{title}:")
        for item in items:
            print(textwrap.fill(item, width=100, initial_indent="  - ", subsequent_indent="    "))
    print("\nPer question:")
    for q in r.questions:
        score = f"{q.score}/100" if q.score is not None else "not scored"
        print(f"  {q.question_id} [{score}] {q.text}")


if __name__ == "__main__":
    asyncio.run(main())
