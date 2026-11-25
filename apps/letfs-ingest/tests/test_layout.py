import re
from pathlib import Path

import pytest
from letfs_ingest.layout import (
    blocks,
    contexts,
    parts,
    write_markdown,
)
from letfs_ingest.tables import externalize_tables


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
    child_names = write_markdown(content, tmp_path, 350, 262144)
    assert len(child_names) >= 2
    assert all(re.fullmatch(r"\d{2,}-part\.md", n) for n in child_names)
    outputs = [tmp_path / "README.md", *[tmp_path / n for n in child_names]]
    combined = "\n".join(path.read_text() for path in outputs)
    for paragraph in paragraphs:
        assert combined.count(paragraph.rstrip()) == 1
    for path in outputs[1:]:
        text = path.read_text()
        assert len(text.encode("utf-8")) <= 4 * 350
        assert re.match(r"# Handbook\n+## Findings\n+", text)
    targets = re.findall(r"\]\(([^)]+\.md)\)", outputs[0].read_text())
    assert targets == child_names


def test_lists_code_and_table_fences_are_indivisible() -> None:
    listing = "- First\n  - Nested entry\n- Second"
    code = "```python\n# literal heading\nprint('retained')\n```"
    table = '```csv\n"multiline\nvalue",2\n```'
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


def test_write_markdown_skips_slide_markers_in_readme_toc(tmp_path: Path) -> None:
    doc = (
        "<!-- slide 1 -->\n\n# Slide 1\n\nExecutive Summary\n\n"
        + ("Detailed opening overview. " * 25)
        + "\n\n<!-- slide 2 -->\n\n# Slide 2\n\nFinancial Projections\n\n"
        + ("More financial details. " * 25)
    )
    part_names = write_markdown(doc, tmp_path, 120, 262144)
    assert part_names == ["01-part.md", "02-part.md"]
    readme = (tmp_path / "README.md").read_text()
    assert "- [Executive Summary](01-part.md)" in readme
    assert "- [Financial Projections](02-part.md)" in readme
    assert "<!-- slide" not in readme


def test_short_slides_pack_together_without_splitting_into_micro_files(
    tmp_path: Path,
) -> None:
    doc = (
        "<!-- slide 1 -->\n\n# Slide 1\n\nAgenda\n\nShort text.\n\n"
        "<!-- slide 2 -->\n\n# Slide 2\n\nNext Steps\n\nMore short text.\n"
    )
    assert write_markdown(doc, tmp_path, 4096, 262144) == []
    assert "Next Steps" in (tmp_path / "README.md").read_text()


def test_part_label_prefers_heading_over_eyebrow_line(tmp_path: Path) -> None:
    doc = (
        "Eyebrow Tag\n\n# Real Section Heading\n\n"
        + ("Paragraph text. " * 40)
        + "\n\nSecond Eyebrow\n\n## Second Heading\n\n"
        + ("Another paragraph. " * 40)
    )
    part_names = write_markdown(doc, tmp_path, 120, 262144)
    assert len(part_names) >= 2
    readme = (tmp_path / "README.md").read_text()
    assert "- [Real Section Heading](01-part.md)" in readme


def test_part_label_skips_shared_document_title_for_subsection_heading(
    tmp_path: Path,
) -> None:
    doc = (
        "# Shared Report Title\n\n## Market Update\n\n"
        + ("Market paragraph. " * 40)
        + "\n\n## Valuation Outlook\n\n"
        + ("Valuation paragraph. " * 40)
    )
    part_names = write_markdown(doc, tmp_path, 120, 262144)
    assert len(part_names) >= 2
    readme = (tmp_path / "README.md").read_text()
    assert "Shared Report Title" not in readme
    assert "- [Market Update](01-part.md)" in readme
    assert "- [Valuation Outlook](" in readme


def test_externalize_tables_numbers_html_and_pipe_tables_sequentially(
    tmp_path: Path,
) -> None:
    html_table = (
        "<table><thead><tr><th>Region</th><th>Metric</th></tr></thead>"
        "<tbody><tr><td>North America Extended Region</td><td>123456789</td></tr>"
        "<tr><td>Europe Middle East and Africa</td><td>987654321</td></tr></tbody></table>"
    )
    pipe_table = "\n".join(
        [
            "| Segment | Value |",
            "| --- | --- |",
            "| Alpha Division Extended Name | 100 |",
            "| Beta Division Extended Name | 200 |",
            "| Gamma Division Extended Name | 300 |",
        ]
    )
    body = f"# Summary\n\nIntro\n\n{html_table}\n\n{pipe_table}\n"
    rewritten = externalize_tables(body, tmp_path, split_tokens=15, max_text=140)
    assert "tables/01-table-01.html" in rewritten
    assert "tables/02-table.csv" in rewritten
    assert (tmp_path / "tables" / "01-table-01.html").is_file()
    assert (tmp_path / "tables" / "02-table.csv").is_file()
