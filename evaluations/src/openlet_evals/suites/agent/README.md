# Agent Evaluation Suite (`suites/agent/` — Speculative Design)

Placeholder documenting how end-to-end Leta agent task evaluation will plug into `openlet_evals.core` without changing the framework layout.

## Planned Modules

- `schema.py`: Task specification (`id`, `workspace`, `prompt`, optional overlay files, APEX-style multi-criterion rubrics, deterministic workspace state checks).
- `sandbox.py`: Manages one live `openlet-env` stack (`openlet_env.Environment`), seeds an isolated fresh workspace per task, applies task overlays, sends the task message to Leta, waits for completion, and runs `unseed()`.
- `capture.py`: Collects final assistant response, created/edited LetFS files, citations, and tool/activity trajectory logs.
- `graders.py`: Combines three grading layers:
  1. **Rubric grader**: LLM-as-a-judge via `openlet_evals.core.judge.JudgeClientPool` / DeepEval `GEval`.
  2. **Workspace state grader**: Deterministic assertions on LetFS files, CSVs, and permissions.
  3. **Trajectory metrics**: Step count, tool errors, citation grounding, token/cost budget.
- `suite.py`: Runs parallel workspace slots via `openlet_evals.core.runner` and emits a standard `EvalRun` JSON compatible with `openlet-eval diff`.
