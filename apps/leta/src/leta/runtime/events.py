"""Public model callbacks share the identities later saved in agent history."""

from langchain_core.callbacks import AsyncCallbackHandler

from leta.history import public_content
from leta.streaming import AgentPublisher


class ModelEvents(AsyncCallbackHandler):
    def __init__(self, publisher: AgentPublisher):
        self.publisher = publisher
        self.message_id = None
        self.text_started = False
        self.tools = {}

    def begin(self, message_id):
        self.message_id = message_id
        self.text_started = False
        self.tools = {}

    async def text(self, content):
        for block in public_content(content):
            if block["type"] != "text" or not block["text"]:
                continue
            if not self.text_started:
                await self.publisher.emit(
                    {
                        "type": "TEXT_MESSAGE_START",
                        "messageId": self.message_id,
                        "role": "assistant",
                    }
                )
                self.text_started = True
            await self.publisher.emit(
                {
                    "type": "TEXT_MESSAGE_CONTENT",
                    "messageId": self.message_id,
                    "delta": block["text"],
                }
            )

    async def tool(self, chunk):
        index = chunk.get("index")
        if index is None:
            return
        value = self.tools.setdefault(
            index, {"id": "", "name": "", "args": "", "started": False}
        )
        for key in ("id", "name", "args"):
            value[key] += chunk.get(key) or ""
        if value["id"] and value["name"]:
            if not value["started"]:
                await self.publisher.emit(
                    {
                        "type": "TOOL_CALL_START",
                        "toolCallId": value["id"],
                        "toolCallName": value["name"],
                        "parentMessageId": self.message_id,
                    }
                )
                value["started"] = True
            if value["args"]:
                await self.publisher.emit(
                    {
                        "type": "TOOL_CALL_ARGS",
                        "toolCallId": value["id"],
                        "delta": value["args"],
                    }
                )
                value["args"] = ""

    async def on_llm_new_token(self, token, *, chunk=None, **kwargs):
        # Summary models run outside DynamicModel's active public block.
        if self.message_id is None or chunk is None:
            return
        message = getattr(chunk, "message", None)
        if message is None:
            return
        await self.text(message.content)
        for item in getattr(message, "tool_call_chunks", []):
            await self.tool(item)

    async def finish(self, message):
        if not self.text_started:
            await self.text(message.content)
        seen = {v["id"] for v in self.tools.values() if v["started"]}
        for call in message.tool_calls:
            if call["id"] not in seen:
                import json

                await self.publisher.emit(
                    {
                        "type": "TOOL_CALL_START",
                        "toolCallId": call["id"],
                        "toolCallName": call["name"],
                        "parentMessageId": self.message_id,
                    }
                )
                await self.publisher.emit(
                    {
                        "type": "TOOL_CALL_ARGS",
                        "toolCallId": call["id"],
                        "delta": json.dumps(call["args"], ensure_ascii=False),
                    }
                )
            await self.publisher.emit(
                {"type": "TOOL_CALL_END", "toolCallId": call["id"]}
            )
        if self.text_started:
            await self.publisher.emit(
                {"type": "TEXT_MESSAGE_END", "messageId": self.message_id}
            )
        self.message_id = None
