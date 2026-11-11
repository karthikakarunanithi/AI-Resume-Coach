"""Golden-set gate (plan 15/18): run the real evaluator on the robustness cases; fail if any expectation breaks.

Calls the configured LLM, so it only runs when asked:  RUN_LLM_EVALS=1 pytest -m llm_eval
CI (week 8) runs it on prompt changes so a prompt that inflates scores can't merge.
"""

import os

import pytest

from evals.dataset import ROBUSTNESS, load_cases
from evals.run_evaluator import run_model

pytestmark = [
    pytest.mark.llm_eval,
    pytest.mark.skipif(os.getenv("RUN_LLM_EVALS") != "1", reason="set RUN_LLM_EVALS=1 (needs API keys)"),
]


async def test_evaluator_passes_robustness_cases():
    from app.config import load_models

    report, _ = await run_model(load_models()["evaluator"]["model"], load_cases(ROBUSTNESS), runs=1)
    failed = [f"{r['case']}: {r['why']}" for r in report.robustness if not r["passed"]]
    assert report.errors == 0, f"{report.errors} evaluator calls errored"
    assert not failed, "Robustness failures:\n" + "\n".join(failed)
