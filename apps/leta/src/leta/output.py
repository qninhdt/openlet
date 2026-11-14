from openlet_sdk.config import JSON

TOKEN_BUDGET = 4096
# Tool previews use the same rough four-byte estimate as Codex output truncation.
BYTE_BUDGET = TOKEN_BUDGET * 4


def preview(value: bytes, budget: int) -> str:
    if len(value) <= budget:
        return value.decode("utf-8", errors="replace")
    marker = b"\n[... output omitted ...]\n"
    head = (budget - len(marker)) // 2
    tail = budget - len(marker) - head
    return (
        value[:head].decode("utf-8", errors="ignore")
        + marker.decode()
        + value[-tail:].decode("utf-8", errors="ignore")
    )


def page(text: str, start_line: int = 1, limit: int = 200) -> dict[str, JSON]:
    if start_line < 1 or not 1 <= limit <= 2000:
        raise ValueError(
            "start_line must be positive and limit must be between 1 and 2000"
        )
    lines = text.splitlines()
    output: list[str] = []
    used = 0
    offset = start_line - 1
    for index in range(offset, min(len(lines), offset + limit)):
        line = f"{index + 1}: {lines[index]}"
        size = len((line + "\n").encode())
        if used + size > BYTE_BUDGET:
            break
        output.append(line)
        used += size
    next_line = offset + len(output) + 1
    more = next_line <= len(lines)
    return {
        "content": "\n".join(output),
        "next_start_line": next_line if more else None,
        "truncated": more,
        **(
            {
                "notice": f"Line {start_line} exceeds the preview budget. Use exec_shell with jq or Python to select the needed fields or part of that line."
            }
            if more and not output
            else {}
        ),
    }
