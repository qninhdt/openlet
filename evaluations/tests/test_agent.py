"""Unit tests for the agent evaluation suite."""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Self

import httpx
import pytest
from deepeval.evaluate.types import EvaluationResult, TestResult
from deepeval.tracing.api import MetricData

from openlet_evals.core.report import diff_runs, render_markdown
from openlet_evals.suites.agent import runner as agent_runner
from openlet_evals.suites.agent import suite as agent_suite
from openlet_evals.suites.agent.runner import (
    ActivityEventItem,
    AssistantMessage,
    Attachment,
    RunStatusResp,
    RunUsage,
    ToolStats,
    TrialArtifact,
    WorkspaceContext,
    collect_outputs,
    execute_trial,
    parse_history,
    render_deliverable,
    resolve_inline_mentions,
    wait_for_run,
)
from openlet_evals.suites.agent.suite import (
    AgentEvalConfig,
    AgentTask,
    GradedTrial,
    aggregate_results,
    grade_trials,
    load_tasks,
    parse_expectation_verdicts,
    validate_tasks,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from deepeval.test_case import LLMTestCase


def test_load_goldens_and_validate_tasks(tmp_path: Path) -> None:
    ds = tmp_path / "retrieval.json"
    ds.write_text(
        json.dumps(
            [
                {
                    "name": "ws-01",
                    "input": "Find EBITDA.",
                    "expectations": {
                        "must": ["States $14.2M."],
                        "must_not": ["Must not cite draft figures."],
                    },
                    "additional_metadata": {
                        "workspace": "ws-a",
                        "tone": "semi-formal",
                        "skills": ["quantitative"],
                        "reference_files": ["/report.xlsx"],
                    },
                }
            ]
        ),
        encoding="utf-8",
    )
    loaded = load_tasks(ds)
    assert len(loaded) == 1
    assert loaded[0].id == "ws-01"
    assert loaded[0].must_not == ["Must not cite draft figures."]

    shared = tmp_path / "ws-a" / "storages" / "shared"
    shared.mkdir(parents=True)
    (shared / "report.xlsx").write_bytes(b"ok")
    assert validate_tasks(loaded, {"ws-a"}, workspaces_dir=tmp_path) == []

    bad = [
        AgentTask(
            id="t-1",
            workspace="ws-a",
            task="Find EBITDA",
            must=["   "],
            reference_files=["/missing.pdf"],
        ),
        AgentTask(id="t-1", workspace="ws-missing", task="Find margin", must=["ok"]),
    ]
    assert len(validate_tasks(bad, {"ws-a"}, workspaces_dir=tmp_path)) == 4


def test_mentions_and_deliverable_rendering() -> None:
    path_map = {
        ("s1", "n1"): "/shared/q3/report.pdf",
        ("s1", "n2"): "/shared/My Folder/Budget (2026).xlsx",
    }
    assert (
        resolve_inline_mentions(
            r"See [Q3 \[Final\]](/letfs/s1/n1), [Budget](/letfs/s1/n2), [X](/letfs/s9/n9).",
            path_map,
        )
        == "See [Q3 [Final]](/shared/q3/report.pdf), [Budget](</shared/My Folder/Budget (2026).xlsx>), X."
    )

    out = render_deliverable(
        [
            Attachment(path="/chat/summary.md", text="# Summary\nEBITDA: $14.2M"),
            Attachment(path="/chat/chart.png", mime="image/png", size=2048),
        ]
    )
    assert out.startswith("# Deliverable Files")
    assert "## `/chat/summary.md`\n# Summary\nEBITDA: $14.2M" in out
    assert "[binary file (image/png): /chat/chart.png, 2048 bytes]" in out
    assert "(No deliverable files were attached" in render_deliverable([])


def test_parse_history_pairs_calls_and_counts_errors() -> None:
    raw_entries = [
        {
            "seq": 2,
            "kind": "tool_result",
            "payload": {
                "tool_call_id": "1",
                "name": "file_read",
                "text": "ok",
                "status": "success",
            },
        },
        {
            "seq": 1,
            "kind": "tool_call",
            "payload": {
                "tool_call_id": "1",
                "name": "file_read",
                "args": {"path": "/shared/a.md"},
            },
        },
        {
            "seq": 3,
            "kind": "tool_call",
            "payload": {
                "tool_call_id": "2",
                "name": "execute",
                "args": {"command": "false"},
            },
        },
        {
            "seq": 4,
            "kind": "tool_result",
            "payload": {
                "tool_call_id": "2",
                "name": "execute",
                "text": "err",
                "status": "error",
            },
        },
    ]
    calls, stats = parse_history(
        [ActivityEventItem.model_validate(item) for item in raw_entries]
    )
    assert [c.name for c in calls] == ["file_read", "execute"]
    assert calls[0].output == "ok"
    assert calls[1].status == "error"
    assert stats == ToolStats(total=2, errors=1, by_tool={"execute": 1, "file_read": 1})


def test_verdict_parsing_and_multi_trial_aggregation() -> None:
    verdicts = parse_expectation_verdicts(
        json.dumps(
            {
                "verdicts": [
                    {
                        "id": "must[0]",
                        "status": "pass",
                        "reason": "ok",
                        "evidence": "$14.2M",
                    }
                ]
            }
        )
    )
    assert len(verdicts) == 1
    assert verdicts[0].status == "pass"
    assert parse_expectation_verdicts("bad") == []

    trials = [
        GradedTrial(
            artifact=TrialArtifact(
                task_id="t1",
                workspace="ws-a",
                trial=1,
                task="q",
                must=["m"],
                status="completed",
                latency_s=10.0,
                usage=RunUsage(
                    input_tokens=1000,
                    cached_input_tokens=200,
                    output_tokens=200,
                    reasoning_tokens=50,
                    cost_usd=0.02,
                    llm_calls=3,
                ),
                tool_stats=ToolStats(
                    total=4, errors=1, by_tool={"file_read": 3, "execute": 1}
                ),
            ),
            passed=True,
            rubric_score=1.0,
        ),
        GradedTrial(
            artifact=TrialArtifact(
                task_id="t1",
                workspace="ws-a",
                trial=2,
                task="q",
                must=["m"],
                status="completed",
                latency_s=20.0,
                usage=RunUsage(
                    input_tokens=2000,
                    cached_input_tokens=400,
                    output_tokens=400,
                    reasoning_tokens=100,
                    cost_usd=0.04,
                    llm_calls=5,
                ),
                tool_stats=ToolStats(total=6, errors=0, by_tool={"file_read": 6}),
            ),
            passed=False,
            rubric_score=0.5,
        ),
    ]
    run = aggregate_results(
        AgentEvalConfig(name="multi", trials=2), trials, wall_s=30.0
    )
    assert run.metrics == {
        "pass_at_1": pytest.approx(0.5),
        "mean_rubric_score": pytest.approx(0.75),
        "pass_at_k": pytest.approx(1.0),
        "pass_pow_k": pytest.approx(0.0),
    }
    assert run.telemetry is not None
    assert run.telemetry["avg_input_tokens"] == 1500.0
    assert run.telemetry["tool_error_rate"] == 0.1
    assert "## Telemetry" in render_markdown(run)
    assert "## Telemetry Diff" in diff_runs(run, run)


def test_grade_trials_matches_by_name_and_zeros_empty_trials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    empty_art = TrialArtifact(
        task_id="t-empty",
        workspace="ws-a",
        trial=1,
        task="q0",
        must=["m0"],
        must_not=["mn0"],
        status="completed",
        messages=[AssistantMessage(content="Answered only in chat with no files")],
        deliverable="(No deliverable files were attached to the final message.)",
    )
    art1 = TrialArtifact(
        task_id="t1",
        workspace="ws-a",
        trial=1,
        task="q1",
        must=["m1"],
        status="completed",
        messages=[AssistantMessage(content="Summary")],
        attachments=[Attachment(path="/chat/a1.md", text="a1")],
        deliverable="a1",
    )
    art2 = TrialArtifact(
        task_id="t2",
        workspace="ws-a",
        trial=1,
        task="q2",
        must=["m2"],
        status="completed",
        messages=[AssistantMessage(content="Summary")],
        attachments=[Attachment(path="/chat/a2.md", text="a2")],
        deliverable="a2",
    )

    seen_names: list[str] = []

    def _metric_data(
        *,
        success: bool,
        score: float,
        reason: str,
        verdicts: list[dict[str, str]],
    ) -> MetricData:
        return MetricData(
            name="Expectations",
            success=success,
            score=score,
            reason=reason,
            strictMode=False,
            evaluationModel=None,
            error=None,
            evaluationCost=None,
            inputTokenCount=None,
            outputTokenCount=None,
            verboseLogs=json.dumps({"verdicts": verdicts}),
            expectationsData=None,
        )

    def fake_eval(
        *,
        test_cases: Sequence[LLMTestCase],
        identifier: str,
        async_config: object,
        cache_config: object,
        error_config: object,
        display_config: object,
    ) -> EvaluationResult:
        _ = (identifier, async_config, cache_config, error_config, display_config)
        seen_names.extend(str(c.name) for c in test_cases)
        # Return results in reverse completion order to ensure positional zip isn't used.
        return EvaluationResult(
            test_results=[
                TestResult(
                    name="t2#t1",
                    success=False,
                    conversational=False,
                    metrics_data=[
                        _metric_data(
                            success=False,
                            score=0.0,
                            reason="bad2",
                            verdicts=[
                                {
                                    "id": "must[0]",
                                    "status": "fail",
                                    "reason": "no",
                                    "evidence": "x",
                                }
                            ],
                        )
                    ],
                ),
                TestResult(
                    name="t1#t1",
                    success=True,
                    conversational=False,
                    metrics_data=[
                        _metric_data(
                            success=True,
                            score=1.0,
                            reason="ok1",
                            verdicts=[
                                {
                                    "id": "must[0]",
                                    "status": "pass",
                                    "reason": "yes",
                                    "evidence": "y",
                                }
                            ],
                        )
                    ],
                ),
            ],
            confident_link=None,
            test_run_id=None,
        )

    def fake_judge(
        *,
        model: str,
        base_url: str,
        api_key: str,
        reasoning_effort: str | None,
    ) -> str:
        _ = (base_url, api_key, reasoning_effort)
        return model

    monkeypatch.setattr(agent_suite, "make_judge", fake_judge)
    monkeypatch.setattr(agent_suite, "evaluate", fake_eval)

    graded = grade_trials(
        [empty_art, art1, art2],
        AgentEvalConfig(name="test"),
        base_url="http://localhost",
        api_key="k",
    )
    assert seen_names == ["t1#t1", "t2#t1"]
    assert graded[0].passed is False
    assert graded[0].rubric_score == 0.0
    assert graded[1].passed is True
    assert graded[1].judge_reason == "ok1"
    assert graded[2].passed is False
    assert graded[2].judge_reason == "bad2"


def test_wait_for_run_survives_cancel_read_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(f"{request.method} {request.url.path}")
        if request.url.path.endswith("/runs"):
            return httpx.Response(
                200, json={"items": [{"id": "run-1", "status": "running"}]}
            )
        if request.url.path.endswith("/cancel"):
            raise httpx.ReadTimeout("blocking cancel_current timed out")
        if request.url.path.endswith("/runs/run-1"):
            return httpx.Response(200, json={"id": "run-1", "status": "running"})
        return httpx.Response(404)

    async def fast_sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr(agent_runner.asyncio, "sleep", fast_sleep)

    async def _run() -> tuple[RunStatusResp, bool]:
        async with httpx.AsyncClient(
            base_url="http://test", transport=httpx.MockTransport(handler)
        ) as client:
            return await wait_for_run(
                client, "/v1/workspaces/w/letas/a", "a", timeout_s=0.01
            )

    run_row, timed_out = asyncio.run(_run())
    assert timed_out is True
    assert run_row.id == "run-1"
    assert any(c.endswith("/cancel") for c in calls)


def test_execute_trial_isolates_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    class FailingClient:
        def __init__(self, **_kwargs: object) -> None:
            pass

        async def __aenter__(self) -> Self:
            return self

        async def __aexit__(self, *_exc: object) -> None:
            return None

        async def post(self, *_args: object, **_kwargs: object) -> httpx.Response:
            raise httpx.ConnectError("gateway unreachable")

    monkeypatch.setattr(agent_runner.httpx, "AsyncClient", FailingClient)
    task = AgentTask(id="t-err", workspace="ws-a", task="q", must=["m"])
    art = asyncio.run(
        execute_trial(
            AgentEvalConfig(name="test"),
            "http://test",
            WorkspaceContext("wid", {}, {}, {}),
            task,
            trial=1,
            idx=0,
        )
    )
    assert art.status == "error"
    assert art.error_code
    assert "ConnectError" in art.error_code
    assert art.task_id == "t-err"


def test_collect_outputs_keeps_only_final_message_chat_attachments() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        p = request.url.path
        if p.endswith(":ensureStorage"):
            return httpx.Response(
                200, json={"storageId": "conv", "rootNodeId": "croot"}
            )
        if p.endswith("/messages"):
            return httpx.Response(
                200,
                json={
                    "messages": [
                        {
                            "id": "m1",
                            "seq": 1,
                            "senderType": "agent",
                            "createdAt": "2026-01-01T00:00:01Z",
                            "content": "Draft",
                            "attachments": [
                                {
                                    "storageId": "conv",
                                    "nodeId": "n-old",
                                    "name": "draft.md",
                                    "mediaType": "text/markdown",
                                    "sizeBytes": 10,
                                }
                            ],
                        },
                        {
                            "id": "m2",
                            "seq": 2,
                            "senderType": "agent",
                            "createdAt": "2026-01-01T00:00:02Z",
                            "content": "Done [Source](/letfs/shared/n-src)",
                            "attachments": [
                                {
                                    "storageId": "shared",
                                    "nodeId": "n-src",
                                    "name": "source.pdf",
                                },
                                {
                                    "storageId": "conv",
                                    "nodeId": "n-final",
                                    "name": "report.md",
                                    "mediaType": "text/markdown",
                                    "sizeBytes": 20,
                                },
                            ],
                        },
                    ],
                    "hasBefore": False,
                },
            )
        if p.endswith("/activity"):
            return httpx.Response(200, json={"items": []})
        if p.endswith("/nodes/n-old"):
            return httpx.Response(
                200, json={"id": "n-old", "parentId": "croot", "name": "draft.md"}
            )
        if p.endswith("/nodes/n-final"):
            return httpx.Response(
                200, json={"id": "n-final", "parentId": "croot", "name": "report.md"}
            )
        if p.endswith("/nodes/n-src"):
            return httpx.Response(
                200, json={"id": "n-src", "parentId": "sroot", "name": "source.pdf"}
            )
        if p.endswith("/nodes/n-final:download"):
            return httpx.Response(200, json={"text": {"content": "# Final Report"}})
        return httpx.Response(404)

    async def _run() -> list[Attachment]:
        async with httpx.AsyncClient(
            base_url="http://test", transport=httpx.MockTransport(handler)
        ) as client:
            _, atts, _, _ = await collect_outputs(
                client,
                "w1",
                "/v1/workspaces/w1/letas/a1",
                "a1",
                "conv-1",
                storage_prefixes={"shared": "/shared"},
                path_cache={("shared", "sroot"): "/shared"},
            )
            return atts

    atts = asyncio.run(_run())
    assert len(atts) == 1
    assert atts[0].path == "/chat/report.md"
    assert atts[0].text == "# Final Report"
