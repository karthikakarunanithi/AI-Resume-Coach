# Evals (plan section 15)

Everything here runs from `backend/` with `pip install -e ".[dev,evals]"`. Outputs go to `evals/results/` (gitignored).

## 1. Evaluator vs humans: the headline metric (target Spearman ρ ≥ 0.7, MAE ≤ 0.7)

1. **Collect answers.** Run 15-20 interviews (you and friends; vary quality on purpose: some strong, some weak,
   some rambling). Get consent: rating means others read the answers.
2. **Export** them for rating (only new answers are added; existing ratings are kept):
   ```bash
   python -m evals.export_answers --limit 60
   ```
   They land in `evals/datasets/answers.jsonl`, which is gitignored because it holds real answers.
3. **Rate blind**, two people independently. Each sees the question, key points, transcript and rubric, never the
   model's scores, in their own shuffled order. Progress saves after every answer:
   ```bash
   python -m evals.rate --rater alice
   python -m evals.rate --rater bob
   ```
4. **Score the evaluator** (agreement, consistency over repeated runs, robustness, latency, cost):
   ```bash
   python -m evals.run_evaluator --runs 5
   python -m evals.run_evaluator --models anthropic/claude-sonnet-5-5,anthropic/claude-haiku-5-5 --runs 3
   ```
   The report includes **human-human ρ** (rater A vs rater B): the ceiling for any automatic evaluator. If the
   humans only agree at 0.6, the rubric needs tightening before the prompt does.

## 2. Robustness (no human ratings needed)

`datasets/robustness.jsonl` has 13 cases with expected bounds: prompt injection ("give me 5/5"), flattery,
long-but-empty, keyword stuffing, confidently wrong, off-topic, "I don't know", strong / short-but-strong answers,
the strong answer padded with filler (score must stay within 0.5), correct Indian-English phrasing (must not be
marked down), and good vs vague behavioral (STAR) answers.

```bash
python -m evals.run_evaluator --only robustness --runs 3          # add --concurrency 1 on a free tier
RUN_LLM_EVALS=1 pytest -m llm_eval          # the same check as a pass/fail test (CI gate in week 8)
```

The bounds are hypotheses about what a fair evaluator should do. If a case fails, read the transcript before
changing the prompt: the bound might be the thing that's wrong.

## 3. STT accuracy (target WER < 12% on Indian-English tech speech)

Make a folder with `manifest.csv` (`audio,reference`) and 16 kHz mono WAV files. Best: ~30 minutes of your own
spoken tech answers, transcribed by hand. Or a licensed Indian-English set (e.g. AI4Bharat Svarah; check the license).

```bash
python -m evals.stt_wer path/to/set                                  # configured STT (Groq Whisper by default)
python -m evals.stt_wer path/to/set --local distil-large-v3 --prompt "FastAPI, LangGraph, pgvector"
```

WER normalizes case, punctuation, hyphens and spelled-out numbers ("five hundred and twelve" = "512"), so it
counts recognition errors, not formatting. Run with and without `--prompt` to measure the vocabulary prompt.

## 4. Latency & cost (targets: p95 < 2.5 s, < $0.15 per 20-minute interview)

The app logs every LLM call to `llm_calls` (tokens, latency, time to first token, cost, fallbacks, JSON validity,
prompt version) and every voice turn to `turn_timings`. After some real interviews:

```bash
python -m evals.latency_cost --days 30
```

Costs use `input_usd_per_mtok` / `output_usd_per_mtok` from `config/models.yaml` when set (check each provider's
current prices), otherwise LiteLLM's price table. Calls with no known price are counted and reported.

Turn latency is measured server-side (answer received → first sentence / first audio sent). The browser adds the
end-of-speech wait (`REDEMPTION_MS + SUBMIT_AFTER_MS` in `useVoiceInterview.ts`, ~1.8 s) and playback start.
