import pytest
from leta.output import BYTE_BUDGET, page


@pytest.mark.parametrize(
    "line", ["A" * 250, "Đề nghị xác nhận phương án triển khai. " * 8]
)
def test_read_continuations_preserve_all_complete_lines(line: str) -> None:
    source = [f"{index} {line}" for index in range(450)]
    text = "\n".join(source)
    actual: list[str] = []
    start = 1
    while True:
        result = page(text, start, limit=200)
        content = result["content"]
        assert isinstance(content, str) and content
        assert len(content.encode()) <= BYTE_BUDGET
        lines = content.splitlines()
        actual.extend(line.split(": ", 1)[1] for line in lines)
        cursor = result["next_start_line"]
        if cursor is None:
            break
        assert cursor == start + len(lines)
        assert result["truncated"] is True
        assert isinstance(cursor, int)
        start = cursor
    assert actual == source


def test_oversized_line_is_reported_without_advancing_past_unread_content() -> None:
    result = page("normal\n" + "x" * BYTE_BUDGET + "\nlast", limit=200)
    assert result["content"] == "1: normal"
    assert result["next_start_line"] == 2
    oversized = page("normal\n" + "x" * BYTE_BUDGET + "\nlast", start_line=2)
    assert oversized["content"] == "" and oversized["next_start_line"] == 2
    assert "Line 2 exceeds" in str(oversized["notice"])


def test_read_limit_is_validated_and_end_of_file_has_no_continuation() -> None:
    assert page("first\nlast", limit=1)["next_start_line"] == 2
    assert page("first\nlast", start_line=2)["next_start_line"] is None
    assert page("first\nlast", start_line=3)["content"] == ""
    with pytest.raises(ValueError):
        page("text", limit=2001)
