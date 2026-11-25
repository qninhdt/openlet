# Openlet Evaluations (`openlet-evals`)

Standalone, minimal evaluation package for Openlet capabilities (`retrieval` and live `agent`). Kept outside the root `uv.workspace` so `deepeval` stays isolated from production lockfiles while sharing `openlet-env` and `openlet-sdk`.

## Quick Start

```bash
uv sync --project evaluations --all-groups

# --- Offline Retrieval Evaluation ---

# Validate retrieval Goldens against .letfs-cache/
uv run --project evaluations openlet-eval retrieval validate \
  --config evaluations/configs/retrieval-baseline.yaml

# Fast deterministic retrieval check (0 LLM calls, ~3.5s)
uv run --project evaluations openlet-eval retrieval run \
  --config evaluations/configs/retrieval-baseline.yaml --no-judge

# Full retrieval benchmark (Recall@k + MRR@5 + DeepEval ContextualRecall & ContextualPrecision)
uv run --project evaluations openlet-eval retrieval run \
  --config evaluations/configs/retrieval-baseline.yaml

# --- Live Leta Agent Evaluation ---

# Validate agent Goldens against workspace datasets
uv run --project evaluations openlet-eval agent validate \
  --config evaluations/configs/agent-baseline.yaml

# Run live Leta agent trials and grade attached /chat deliverable files with DeepEval Expectations
uv run --project evaluations openlet-eval agent run \
  --config evaluations/configs/agent-baseline.yaml --keep-stack

# Re-grade previously saved trial artifacts without re-running Leta
uv run --project evaluations openlet-eval agent grade \
  .local/evals/runs/<run>.artifacts.json \
  --config evaluations/configs/agent-baseline.yaml

# --- Compare Runs ---

uv run --project evaluations openlet-eval diff \
  .local/evals/runs/base.json .local/evals/runs/cand.json
```

## Layout

- `configs/`: YAML presets tracked in git (`retrieval-baseline.yaml`, `agent-baseline.yaml`).
- `src/openlet_evals/core/`: `judge.py` (`deepeval.models.OpenAIModel` factory) + `report.py` (summary, Markdown, A/B diff).
- `src/openlet_evals/suites/retrieval/`: `corpus.py`, `search.py`, `suite.py`.
- `src/openlet_evals/suites/agent/`: `runner.py` (isolated Docker stack, workspace seeding, live Leta execution, final-message `/chat` attachment collection) + `suite.py` (Golden validation, DeepEval `Expectations` file-deliverable grading, reporting).
- `.local/evals/`: Gitignored run outputs, trial artifacts, and cached query embeddings.
