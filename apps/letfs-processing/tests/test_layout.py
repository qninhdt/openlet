import re

import pytest
from docling_core.types.doc import (
    DocItemLabel,
    DoclingDocument,
    ImageRef,
    TableCell,
    TableData,
)
from PIL import Image

from openlet_processor.exporters import markdown
from openlet_processor.layout import document_layout
from openlet_processor.text_split import estimate_tokens, layout_limits, split_text


def build(parts=3, chapters=3):
    doc = DoclingDocument(name="book")
    doc.add_heading("Wrapper", level=1)
    doc.add_text(label=DocItemLabel.TEXT, text="PreambleUnique.")
    for part in range(parts):
        doc.add_heading(f"PartUnique{part}", level=2)
        doc.add_text(label=DocItemLabel.TEXT, text=f"IntroUnique{part}.")
        for chapter in range(chapters):
            doc.add_heading(f"ChapterUnique{part}x{chapter}", level=3)
            doc.add_text(
                label=DocItemLabel.TEXT,
                text=f"BodyUnique{part}x{chapter}. " + "substantial prose " * 40,
            )
    return doc


@pytest.mark.parametrize("split,depth", [(10000, 0), (1000, 1), (100, 2)])
@pytest.mark.parametrize("kind", ["pdf", "docx"])
def test_global_layout_preserves_every_text_once(
    split, depth, kind, tmp_path, monkeypatch
):
    monkeypatch.setenv("MIN_LEAF_TOKENS", "20")
    monkeypatch.setenv("SPLIT_TOKENS", str(split))
    doc = build()
    markdown(doc, tmp_path, kind)
    files = list(tmp_path.rglob("*.md"))
    assert max(len(p.relative_to(tmp_path).parts) for p in files) == max(1, depth)
    if depth == 0:
        assert [p.name for p in files] == ["README.md"]
    elif depth == 1:
        assert len(files) == 4
    else:
        assert len(files) == 13
        assert len(list(tmp_path.glob("*-untitled"))) == 3
    actual = "\n".join(p.read_text() for p in files)
    for item in doc.texts:
        assert actual.count(item.text) == 1
    for folder in [tmp_path] + [p for p in tmp_path.rglob("*") if p.is_dir()]:
        assert (folder / "README.md").is_file()
    assert "PreambleUnique" in (tmp_path / "README.md").read_text()


def test_single_long_chapter_remains_one_readme(tmp_path, monkeypatch):
    monkeypatch.setenv("MIN_LEAF_TOKENS", "1")
    monkeypatch.setenv("SPLIT_TOKENS", "20")
    markdown(build(parts=1, chapters=1), tmp_path, "pdf")
    assert [p.name for p in tmp_path.iterdir()] == ["README.md"]


def test_table_cell_headings_do_not_split_the_document():
    doc = DoclingDocument(name="table-headings")
    doc.add_heading("First section", level=2)
    table = doc.add_table(data=TableData(num_rows=0, num_cols=0, table_cells=[]))
    for number in range(2):
        doc.add_heading(f"Cell heading {number}", level=1, parent=table)
        doc.add_text(label=DocItemLabel.TEXT, text="Cell prose. " * 40, parent=table)
    doc.add_heading("Second section", level=2)
    doc.add_text(label=DocItemLabel.TEXT, text="Second prose. " * 40)
    items = list(doc.iterate_items(with_groups=True, traverse_pictures=True))
    sections = document_layout(items, minimum=1, split=1)
    starts = [items[section.start][0] for section in sections[1:]]
    assert [item.text for item in starts] == ["First section", "Second section"]


def test_adjacent_tiny_sections_merge_without_losing_headings(tmp_path, monkeypatch):
    monkeypatch.setenv("MIN_LEAF_TOKENS", "20")
    monkeypatch.setenv("SPLIT_TOKENS", "30")
    doc = DoclingDocument(name="short-sections")
    for n in range(5):
        doc.add_heading(f"Heading{n}")
        doc.add_text(
            label=DocItemLabel.TEXT, text=("body " * 40 if n in (1, 3) else "tiny")
        )
    markdown(doc, tmp_path, "docx")
    files = list(tmp_path.glob("*-untitled.md"))
    assert len(files) == 2
    text = "\n".join(p.read_text() for p in files)
    for n in range(5):
        assert text.count(f"Heading{n}") == 1


def test_independent_media_counters_and_nearest_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("MIN_LEAF_TOKENS", "20")
    monkeypatch.setenv("SPLIT_TOKENS", "100")
    doc = build()
    for _ in range(10):
        doc.add_picture(image=ImageRef.from_pil(Image.new("RGB", (2, 2)), 72))
    doc.add_table(
        data=TableData(
            num_rows=1,
            num_cols=1,
            table_cells=[
                TableCell(
                    text="TableOnlyUnique",
                    start_row_offset_idx=0,
                    end_row_offset_idx=1,
                    start_col_offset_idx=0,
                    end_col_offset_idx=1,
                )
            ],
        )
    )
    markdown(doc, tmp_path, "pdf")
    folder = tmp_path / "3-untitled"
    assert {p.name for p in folder.glob("*.png")} == {
        f"untitled-{n:02}.png" for n in range(1, 11)
    }
    assert (folder / "untitled-1.csv").read_text().strip() == "TableOnlyUnique"
    text = "\n".join(p.read_text() for p in tmp_path.rglob("*.md"))
    assert "TableOnlyUnique" not in text
    assert not (tmp_path / "images").exists()
    for path in tmp_path.rglob("*.md"):
        for link in re.findall(r"\]\(([^)]+)\)", path.read_text()):
            assert (path.parent / link).is_file()


@pytest.mark.parametrize(
    "value", ["Việt Nam 日本語 👋 " * 30, "x" * 1000, "a\nb\n" * 100]
)
def test_token_split_preserves_original_without_overlap(value):
    chunks = split_text(value, 20)
    assert "".join(chunks) == value
    assert all(estimate_tokens(chunk) <= 20 for chunk in chunks)


@pytest.mark.parametrize("minimum,split", [("0", "10"), ("11", "10"), ("bad", "10")])
def test_invalid_layout_limits_fail_at_startup(monkeypatch, minimum, split):
    monkeypatch.setenv("MIN_LEAF_TOKENS", minimum)
    monkeypatch.setenv("SPLIT_TOKENS", split)
    with pytest.raises(ValueError):
        layout_limits()


def test_structural_padding_and_single_subsection_group(tmp_path, monkeypatch):
    monkeypatch.setenv("MIN_LEAF_TOKENS", "20")
    monkeypatch.setenv("SPLIT_TOKENS", "300")
    markdown(build(parts=10, chapters=1), tmp_path, "pdf")
    assert (tmp_path / "01-untitled.md").is_file()
    assert (tmp_path / "10-untitled.md").is_file()


def test_level_two_keeps_single_subsection_intro_in_group_readme(tmp_path, monkeypatch):
    monkeypatch.setenv("MIN_LEAF_TOKENS", "20")
    monkeypatch.setenv("SPLIT_TOKENS", "100")
    doc = build(parts=2, chapters=3)
    doc.add_heading("Final part", level=2)
    doc.add_text(label=DocItemLabel.TEXT, text="Final introduction.")
    doc.add_heading("Only subsection", level=3)
    doc.add_text(label=DocItemLabel.TEXT, text="Single body. " * 80)
    markdown(doc, tmp_path, "docx")
    assert "Final introduction." in (tmp_path / "3-untitled/README.md").read_text()
    leaf = (tmp_path / "3-untitled/1-untitled.md").read_text()
    assert "Final introduction." not in leaf
    assert "Only subsection" in leaf and "Single body." in leaf
