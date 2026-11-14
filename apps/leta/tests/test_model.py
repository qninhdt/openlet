import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from typing import cast

import pytest
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.utils.function_calling import convert_to_openai_tool
from langfuse.model import TextPromptClient
from leta.config import Services
from leta.runtime.agent import ExecutionModel
from leta.runtime.model import ChatModel
from leta.runtime.tools import file_write
from litellm import token_counter  # pyright: ignore[reportUnknownVariableType]  # Upstream tokenizer arguments are not fully typed.
from litellm.types.llms.openai import AllMessageValues, ChatCompletionToolParam  # pyright: ignore[reportMissingTypeStubs]  # Upstream package does not publish type stubs.
from openlet_sdk.config import JSON
from openlet_sdk.inference import InferenceSettings


@pytest.mark.parametrize("stream", [False, True])
async def test_http_tool_history_preserves_unicode_and_reasoning(stream: bool) -> None:
    received: list[dict[str, JSON]] = []

    class Endpoint(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            pass

        def do_POST(self) -> None:
            received.append(
                json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            )
            self.send_response(200)
            self.send_header(
                "Content-Type", "text/event-stream" if stream else "application/json"
            )
            self.end_headers()
            if stream:
                chunks: list[dict[str, JSON]] = [
                    {
                        "index": 0,
                        "delta": {"role": "assistant", "content": "OK"},
                        "finish_reason": None,
                    },
                    {"index": 0, "delta": {}, "finish_reason": "stop"},
                ]
                for chunk in chunks:
                    value: dict[str, JSON] = {
                        "id": "fixture",
                        "object": "chat.completion.chunk",
                        "created": 1,
                        "model": "gpt-4o",
                        "choices": [chunk],
                    }
                    self.wfile.write(f"data: {json.dumps(value)}\n\n".encode())
                self.wfile.write(b"data: [DONE]\n\n")
            else:
                self.wfile.write(
                    json.dumps(
                        {
                            "id": "fixture",
                            "object": "chat.completion",
                            "created": 1,
                            "model": "gpt-4o",
                            "choices": [
                                {
                                    "index": 0,
                                    "message": {"role": "assistant", "content": "OK"},
                                    "finish_reason": "stop",
                                }
                            ],
                            "usage": {
                                "prompt_tokens": 1,
                                "completion_tokens": 1,
                                "total_tokens": 2,
                            },
                        }
                    ).encode()
                )

    arguments = {"path": "~/báo_cáo.md", "content": "Đã duyệt phương án triển khai."}
    reasoning = "Cần giữ nguyên nội dung tiếng Việt."
    messages: list[BaseMessage] = [
        HumanMessage(content="Hãy tạo báo cáo tiếng Việt."),
        AIMessage(
            content="",
            tool_calls=[{"id": "write", "name": "file_write", "args": arguments}],
            additional_kwargs={"reasoning_content": reasoning},
        ),
        ToolMessage(content="Đã ghi báo cáo.", tool_call_id="write", name="file_write"),
    ]
    server = ThreadingHTTPServer(("127.0.0.1", 0), Endpoint)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        model = ChatModel(
            model="litellm_proxy/openai/gpt-4o",
            api_base=f"http://127.0.0.1:{server.server_port}/v1",
            api_key="local-fixture-only",
            max_retries=0,
            model_kwargs={"num_retries": 0},
        )
        chat = model.bind_tools([file_write])  # pyright: ignore[reportUnknownMemberType]  # Upstream overload includes untyped callable tools.
        if stream:
            async for _ in chat.astream(messages):
                pass
        else:
            await chat.ainvoke(messages)
    finally:
        server.shutdown()
        server.server_close()
        thread.join()

    assert len(received) == 1
    assert received[0]["model"] == "openai/gpt-4o"
    sent = cast(list[dict[str, JSON]], received[0]["messages"])
    calls = cast(list[dict[str, JSON]], sent[1]["tool_calls"])
    function = cast(dict[str, JSON], calls[0]["function"])
    encoded = function["arguments"]
    assert isinstance(encoded, str)
    assert "\\u" not in encoded and "Đã duyệt" in encoded
    assert json.loads(encoded) == arguments
    assert sent[0]["content"] == messages[0].content
    assert sent[1]["reasoning_content"] == reasoning
    assert (
        sent[2]["tool_call_id"] == "write" and sent[2]["content"] == "Đã ghi báo cáo."
    )
    assert received[0]["tools"]
    runtime = ExecutionModel(
        cast(Services, None),
        InferenceSettings(model="fixture", max_tokens=1024),
        cast(TextPromptClient, None),
        cast(TextPromptClient, None),
        [file_write],
        "",
    )
    runtime.chat = model
    assert runtime.count_tokens(messages, include_tools=True) == token_counter(
        model="openai/gpt-4o",
        messages=cast(list[AllMessageValues], sent),
        tools=cast(list[ChatCompletionToolParam], received[0]["tools"]),
    )


def test_context_counter_includes_replayed_reasoning_and_tools() -> None:
    runtime = ExecutionModel(
        cast(Services, None),
        InferenceSettings(model="fixture", max_tokens=1024),
        cast(TextPromptClient, None),
        cast(TextPromptClient, None),
        [file_write],
        "",
    )
    runtime.chat = ChatModel(model="litellm_proxy/gpt-4o", api_key="local-fixture-only")
    messages = [
        AIMessage(
            content="Kết quả",
            additional_kwargs={"reasoning_content": "Đã kiểm tra dữ liệu."},
        )
    ]
    expected = token_counter(
        model="gpt-4o",
        messages=cast(
            list[AllMessageValues],
            [
                {
                    "role": "assistant",
                    "content": "Kết quả",
                    "reasoning_content": "Đã kiểm tra dữ liệu.",
                }
            ],
        ),
        tools=cast(list[ChatCompletionToolParam], [convert_to_openai_tool(file_write)]),
    )
    assert runtime.count_tokens(messages, include_tools=True) == expected
    assert runtime.count_tokens(messages, include_tools=True) > runtime.count_tokens(
        messages
    )
    assert runtime.count_tokens(messages) > runtime.count_tokens(
        [AIMessage(content="Kết quả")]
    )
