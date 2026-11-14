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
                "notice": f"Line {start_line} exceeds the preview budget. Use execute with jq or Python to select the needed fields or part of that line."
            }
            if more and not output
            else {}
        ),
    }


def text_page(text: str, start_line: int = 1, limit: int | None = None) -> str:
    if start_line < 1 or (limit is not None and not 1 <= limit <= 2000):
        raise ValueError(
            "start_line must be positive; limit must be between 1 and 2000"
        )
    lines = text.splitlines(keepends=True)
    offset = start_line - 1
    end = len(lines) if limit is None else min(len(lines), offset + limit)
    selected: list[str] = []
    used = 0
    for line in lines[offset:end]:
        size = len(line.encode())
        if used + size > BYTE_BUDGET:
            break
        selected.append(line)
        used += size
    next_line = start_line + len(selected)
    body = "".join(selected)
    if next_line <= len(lines):
        if not selected:
            return f"Line {start_line} exceeds the preview budget. Use execute with jq or Python to select fields or a substring."
        return body + f"\n[More content. Continue with start_line={next_line}.]"
    return body or ("(empty file)" if not text else "(end of file)")
