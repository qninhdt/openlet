import re
from pathlib import Path

import pytest
from letfs_ingest.layout import (
    blocks,
    contexts,
    parts,
    write_markdown,
)


@pytest.mark.parametrize("target,byte_limit", [(0, 100), (-1, 100), (100, 0)])
def test_invalid_layout_limits_fail_clearly(target: int, byte_limit: int) -> None:
    with pytest.raises(ValueError, match="positive"):
        parts("text", target, byte_limit)


def test_split_preserves_content_and_context_with_serialized_budget(
    tmp_path: Path,
) -> None:
    paragraphs = [
        f"Evidence {i}: " + "Việt Nam — thông tin đầy đủ. " * 8 for i in range(12)
    ]
    content = "# Handbook\n\n## Findings\n\n" + "\n\n".join(paragraphs)
    write_markdown(content, tmp_path, 350, 262144)
    outputs = [tmp_path / "README.md", *sorted(tmp_path.glob("part-*.md"))]
    assert len(outputs) > 2
    combined = "\n".join(path.read_text() for path in outputs)
    for paragraph in paragraphs:
        assert combined.count(paragraph.rstrip()) == 1
    for path in outputs:
        text = path.read_text()
        assert len(text.encode("utf-8")) <= 4 * 350
        assert re.match(r"# Handbook\n+## Findings\n+", text)
    targets = re.findall(r"\]\(([^)]+\.md)\)", outputs[0].read_text())
    assert targets == [path.name for path in outputs[1:]]
    assert not (tmp_path / "part-001.md").exists()


def test_lists_code_and_table_fences_are_indivisible() -> None:
    listing = "- First\n  - Nested entry\n- Second"
    code = "```python\n# literal heading\nprint('retained')\n```"
    table = '<!-- artifact-table {"ref":"#/tables/0"} -->\n\n```csv\n"multiline\nvalue",2\n```'
    content = "# Topic\n\n" + "\n\n".join([listing, code, table])
    units = blocks(content)
    for block in [listing, code, table]:
        assert sum(block in unit for unit in units) == 1
    output = parts(content, 35, 262144)
    for block in [listing, code, table]:
        assert sum(block in part for part in output) == 1


def test_context_ignores_empty_headings_and_does_not_leak_between_siblings() -> None:
    prefixes = contexts(["# Topic\n\nbody", "more", "# Other\n\nbody", "# \n\nnext"])
    assert prefixes[1] == "# Topic\n\n"
    assert prefixes[2] == ""
    assert not any(re.search(r"^#+\s*$", prefix, re.M) for prefix in prefixes)


def test_slide_content_stays_together_without_previous_slide_heading() -> None:
    slides = [
        f"<!-- slide {i} -->\n\n# Slide {i}\n\n" + "Evidence " * 50 for i in range(1, 5)
    ]
    output = parts("\n\n".join(slides), 100, 262144)
    assert len(output) >= 4
    for i, slide in enumerate(slides, 1):
        part = next(part for part in output if f"<!-- slide {i} -->" in part)
        assert slide.rstrip() in part and (i == 1 or f"# Slide {i - 1}" not in part)


def test_byte_limit_splits_at_blocks_and_rejects_an_oversized_atom() -> None:
    paragraphs = [f"Evidence {i}: " + "x " * 100 for i in range(6)]
    output = parts("\n\n".join(paragraphs), 4096, 1000)
    assert len(output) > 1 and all(len(text.encode()) <= 1000 for text in output)
    for paragraph in paragraphs:
        assert sum(paragraph.rstrip() in part for part in output) == 1
    with pytest.raises(ValueError, match="artifact text exceeds"):
        parts("x " * 1000, 4096, 100)


def test_oversized_atomic_content_is_retained_without_truncation() -> None:
    text = "Complete original paragraph " * 200
    output = parts(text, 100, 262144)
    assert len(output) == 1 and output[0].strip() == text.strip()
