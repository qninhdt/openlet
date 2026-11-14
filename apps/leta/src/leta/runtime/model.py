import json
from typing import cast

from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.tools import BaseTool
from langchain_core.utils.function_calling import convert_to_openai_tool
from langchain_litellm import ChatLiteLLM
from litellm import token_counter  # pyright: ignore[reportUnknownVariableType]  # Upstream tokenizer arguments are not fully typed.
from litellm.types.llms.openai import AllMessageValues, ChatCompletionToolParam  # pyright: ignore[reportMissingTypeStubs]  # Upstream package does not publish type stubs.
from openlet_sdk.config import JSON


class ChatModel(ChatLiteLLM):
    def _create_message_dicts(
        self, messages: list[BaseMessage], stop: list[str] | None
    ) -> tuple[list[dict[str, JSON]], dict[str, JSON]]:
        # langchain-litellm 0.11.2 has no option to preserve Unicode in tool arguments.
        payload, params = super()._create_message_dicts(messages, stop)
        for message, value in zip(messages, payload, strict=True):
            if isinstance(message, AIMessage) and message.tool_calls:
                calls = cast(list[dict[str, JSON]], value["tool_calls"])
                for call, serialized in zip(message.tool_calls, calls, strict=True):
                    function = cast(dict[str, JSON], serialized["function"])
                    function["arguments"] = json.dumps(call["args"], ensure_ascii=False)
        return payload, params

    def count_tokens(
        self, messages: list[BaseMessage], tools: list[BaseTool] | None = None
    ) -> int:
        payload, _ = self._create_message_dicts(messages, None)
        return token_counter(
            model=self.model,
            messages=cast(list[AllMessageValues], payload),
            tools=cast(
                list[ChatCompletionToolParam],
                [convert_to_openai_tool(tool) for tool in tools],
            )
            if tools
            else None,
        )
