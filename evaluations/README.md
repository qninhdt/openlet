# Openlet Evaluations (`openlet-evals`)

Standalone, minimal evaluation package for Openlet capabilities (`retrieval`, speculative `agent`). Kept outside the root `uv.workspace` so `deepeval` stays isolated from production lockfiles while sharing `openlet-env` and `openlet-sdk`.

## Quick Start

```bash
uv sync --project evaluations --all-groups

# Validate Goldens against .letfs-cache/
uv run --project evaluations openlet-eval retrieval validate --config evaluations/configs/retrieval-baseline.yaml

# Fast deterministic retrieval check (0 LLM calls, ~3.5s)
uv run --project evaluations openlet-eval retrieval run \
  --config evaluations/configs/retrieval-baseline.yaml --no-judge

# Full retrieval benchmark (Recall@k + MRR@5 + DeepEval ContextualRecall & ContextualPrecision)
uv run --project evaluations openlet-eval retrieval run \
  --config evaluations/configs/retrieval-baseline.yaml

# Compare two runs
uv run --project evaluations openlet-eval diff \
  .local/evals/runs/base.json .local/evals/runs/cand.json
```

## Layout

- `configs/`: YAML presets tracked in git (`retrieval-baseline.yaml`).
- `src/openlet_evals/core/`: `judge.py` (`deepeval.models.OpenAIModel` factory) + `report.py` (summary, Markdown, A/B diff).
- `src/openlet_evals/suites/retrieval/`: `corpus.py`, `search.py`, `suite.py`.
- `src/openlet_evals/suites/agent/`: Speculative design placeholder (`README.md`).
- `.local/evals/`: Gitignored run outputs and cached query embeddings.
