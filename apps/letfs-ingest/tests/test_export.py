import csv
import re
from collections.abc import Iterator
from pathlib import Path
from typing import cast
from unittest.mock import patch

import pytest
from docling.datamodel.accelerator_options import AcceleratorOptions
from docling.datamodel.pipeline_options import ConvertPipelineOptions
from docling.models.stages.picture_classifier.document_picture_classifier import (
    DocumentPictureClassifier,
)
from docling_core.types.doc.common.reference import ImageRef
from docling_core.types.doc.document import DoclingDocument
from docling_core.types.doc.labels import DocItemLabel
from letfs_ingest.convert import InvalidDocument, convert, preflight
from letfs_ingest.export import document
from markdown_it import MarkdownIt
from openlet_sdk.config import Config
from openpyxl import Workbook
from PIL import Image


@pytest.fixture(name="config")
def export_config(config: Config, tmp_path: Path) -> Iterator[Config]:
    config["services"]["letfs_ingest"]["cpu"]["docling_models_path"] = str(tmp_path)
    # Export tests exercise document conversion without loading model weights.
    with patch(
        "docling.pipeline.base_pipeline.DocumentPictureClassifier",
        return_value=DocumentPictureClassifier(
            enabled=False,
            artifacts_path=tmp_path,
            options=ConvertPipelineOptions().picture_classification_options,
            accelerator_options=AcceleratorOptions(device="cpu"),
            enable_remote_services=False,
        ),
    ):
        yield config


def exported_tables(folder: Path) -> list[list[list[str]]]:
    result: list[list[list[str]]] = []
    for path in sorted(folder.rglob("*.md")):
        for token in MarkdownIt("commonmark").parse(path.read_text()):
            if token.type == "fence" and token.info == "csv":
                result.append(list(csv.reader(token.content.splitlines(keepends=True))))
    for path in sorted(folder.rglob("*.csv")):
        with path.open(newline="") as stream:
            result.append(list(csv.reader(stream)))
    return result


def test_spreadsheet_preserves_ordinary_tables_formulas_and_outside_cells(
    tmp_path: Path, config: Config
) -> None:
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet.title = "Sales"
    sheet.append(["Quarter", "Revenue"])
    sheet.append(["Q1", 100])
    sheet.append(["Q2", 250])
    sheet["D5"] = "Forecast note"
    sheet["D7"] = "=1+2"
    sheet["A10"], sheet["B10"] = "Team", "Budget"
    sheet["A11"], sheet["B11"] = "Research", 70
    workbook.create_sheet("Empty")
    picture = tmp_path / "plot.png"
    Image.new("RGB", (12, 12), "blue").save(picture)
    from openpyxl.drawing.image import Image as ExcelImage

    sheet.add_image(ExcelImage(picture), "F10")
    source = tmp_path / "input.xlsx"
    workbook.save(source)
    output = tmp_path / "artifacts"
    output.mkdir()
    convert(
        source,
        output,
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        config,
        source_name="Sales report 2026.xlsx",
    )
    assert (output / "README.md").read_text().startswith("# Sales report 2026\n")
    assert "Sales" in (output / "README.md").read_text()
    markdown = "\n".join(p.read_text() for p in output.glob("*.md"))
    assert "D5: Forecast note" in markdown
    assert "D7: =1+2" in markdown
    data = exported_tables(output)[0]
    assert data[:3] == [["Quarter", "Revenue"], ["Q1", "100"], ["Q2", "250"]]
    assert data[9:11] == [["Team", "Budget"], ["Research", "70"]]
    assert "# Empty" in markdown
    assert list(output.glob("*.png"))


def test_document_sections_keep_full_text_and_relative_images(tmp_path: Path) -> None:
    doc = DoclingDocument(name="report")
    doc.add_text(label=DocItemLabel.TEXT, text="Introduction")
    for number in range(3):
        doc.add_heading(text=f"Section {number}", level=1)
        doc.add_text(
            label=DocItemLabel.TEXT,
            text=f"Evidence {number}: " + "complete content " * 200,
        )
    image = Image.new("RGB", (8, 8), "red")
    ref = ImageRef.from_pil(image, dpi=72)
    doc.add_picture(image=ref)
    document(doc, tmp_path, split_tokens=100, max_text_bytes=262144)
    markdown = list(tmp_path.rglob("*.md"))
    combined = "\n".join(path.read_text() for path in markdown)
    for number in range(3):
        assert combined.count(f"Evidence {number}:") == 1
    for path in markdown:
        for target in re.findall(r"\]\(([^)]+)\)", path.read_text()):
            assert (path.parent / target).is_file(), (path, target)
    assert list(tmp_path.rglob("*.png"))
    assert all(not p.is_dir() for p in tmp_path.iterdir())


@pytest.mark.parametrize("threshold", [10000, 400, 50])
def test_document_layout_preserves_nested_sections_once(
    tmp_path: Path, threshold: int
) -> None:
    doc = DoclingDocument(name="handbook")
    doc.add_heading("Handbook", level=1)
    doc.add_text(label=DocItemLabel.TEXT, text="Preamble retained.")
    for part in range(2):
        doc.add_heading(f"Part {part}", level=2)
        doc.add_text(label=DocItemLabel.TEXT, text=f"Introduction {part}.")
        for section in range(2):
            doc.add_heading(f"Topic {part}-{section}", level=3)
            doc.add_text(
                label=DocItemLabel.TEXT,
                text=f"Evidence {part}-{section}. " + "Substantial prose. " * 25,
            )
    document(doc, tmp_path, threshold, max_text_bytes=262144)
    outputs = list(tmp_path.rglob("*.md"))
    assert outputs and not any(path.is_dir() for path in tmp_path.iterdir())
    combined = "\n".join(path.read_text() for path in outputs)
    for item in doc.texts:
        if item.label == DocItemLabel.TEXT:
            assert combined.count(item.text.rstrip()) == 1


@pytest.mark.parametrize("wrapper", ["sdt", "ins"])
def test_word_keeps_wrapped_runs_and_links_csv_in_place(
    tmp_path: Path, config: Config, wrapper: str
) -> None:
    from docx import Document
    from docx.oxml import OxmlElement
    from lxml import etree

    word = Document()
    word.add_paragraph("Before table.")
    table = word.add_table(rows=2, cols=2)
    table.cell(0, 1).text = "Amount"
    table.cell(1, 0).text = "Revenue"
    table.cell(1, 1).text = "120"
    cell = table.cell(0, 0)
    paragraph = cell.paragraphs[0]
    paragraph.add_run("Visible ")
    run = paragraph.add_run("controlled content")
    element = cast(etree._Element, OxmlElement(f"w:{wrapper}"))  # pyright: ignore[reportPrivateUsage]  # lxml's public XML element type uses an underscore.
    if wrapper == "sdt":
        nested = cast(etree._Element, OxmlElement("w:sdtContent"))  # pyright: ignore[reportPrivateUsage]
        element.append(nested)
    else:
        nested = element
    # python-docx exposes no public API for inserting compatibility markup.
    run_xml = cast(etree._Element, run._r)  # pyright: ignore[reportPrivateUsage]
    run_xml.addprevious(element)
    nested.append(run_xml)
    paragraph.add_run(" retained.")
    word.add_paragraph("After table.")
    source = tmp_path / "contract.docx"
    word.save(str(source))
    output = tmp_path / "output"
    output.mkdir()
    convert(
        source,
        output,
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        config,
    )
    markdown = (output / "README.md").read_text()
    assert (
        markdown.index("Before table.")
        < markdown.index("```csv")
        < markdown.index("After table.")
    )
    assert "Visible controlled content retained." in exported_tables(output)[0][0][0]
    assert not list(output.glob("*.csv"))


def test_powerpoint_keeps_untitled_slides_and_compatibility_shapes(
    tmp_path: Path, config: Config
) -> None:
    from lxml import etree
    from pptx import Presentation
    from pptx.util import Inches

    deck = Presentation()
    slide = deck.slides.add_slide(deck.slide_layouts[6])
    shape = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(4), Inches(1))
    shape.text = "Compatibility text survives"
    mc = "http://schemas.openxmlformats.org/markup-compatibility/2006"
    a14 = "http://schemas.microsoft.com/office/drawing/2010/main"
    wrapper = etree.Element(f"{{{mc}}}AlternateContent", nsmap={"mc": mc, "a14": a14})
    branch = etree.SubElement(wrapper, f"{{{mc}}}Choice", Requires="a14")
    cast(etree._Element, shape.element).addprevious(wrapper)  # pyright: ignore[reportPrivateUsage]  # lxml's public XML element type uses an underscore.
    branch.append(shape.element)
    picture = tmp_path / "figure.png"
    Image.new("RGB", (10, 10), "green").save(picture)
    shape = slide.shapes.add_picture(str(picture), Inches(2), Inches(3))
    fallback = etree.Element(
        f"{{{mc}}}AlternateContent", nsmap={"mc": mc, "unknown": "urn:unsupported"}
    )
    etree.SubElement(fallback, f"{{{mc}}}Choice", Requires="unknown")
    branch = etree.SubElement(fallback, f"{{{mc}}}Fallback")
    cast(etree._Element, shape.element).addprevious(fallback)  # pyright: ignore[reportPrivateUsage]
    branch.append(shape.element)
    slide = deck.slides.add_slide(deck.slide_layouts[6])
    slide.shapes.add_textbox(
        Inches(1), Inches(1), Inches(4), Inches(1)
    ).text = "Untitled second slide"
    source = tmp_path / "brief.pptx"
    deck.save(str(source))
    output = tmp_path / "output"
    output.mkdir()
    convert(
        source,
        output,
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        config,
    )
    markdown = (output / "README.md").read_text()
    assert "<!-- slide 1 -->" in markdown and "<!-- slide 2 -->" in markdown
    assert (
        markdown.index("Compatibility text survives")
        < markdown.index("<!-- slide 2 -->")
        < markdown.index("Untitled second slide")
    )
    assert list(output.glob("*.png"))
    for target in re.findall(r"\]\(([^)]+)\)", markdown):
        assert (output / target).is_file()


def test_input_limits_reject_expanded_office_and_oversized_spreadsheet(
    tmp_path: Path, config: Config
) -> None:
    from zipfile import ZipFile

    source = tmp_path / "large.docx"
    with ZipFile(source, "w") as archive:
        archive.writestr("word/document.xml", "x" * 2048)
    limits = config["services"]["letfs_ingest"]["cpu"]["limits"]
    limits["max_office_expanded_bytes"] = 1024
    with pytest.raises(InvalidDocument, match="expanded size"):
        preflight(
            source,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            config,
        )
    limits["max_office_expanded_bytes"] = 536870912
    limits["max_spreadsheet_cells"] = 3
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet.append(["Name", "Amount"])
    sheet.append(["Sales", 40])
    source = tmp_path / "large.xlsx"
    workbook.save(source)
    with pytest.raises(InvalidDocument, match="sheet/cell"):
        preflight(
            source,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            config,
        )


def test_formula_fallback_preserves_crop_and_reuses_identical_pictures(
    tmp_path: Path,
) -> None:
    from docling_core.types.doc.base import BoundingBox, CoordOrigin, Size
    from docling_core.types.doc.common.reference import ProvenanceItem

    doc = DoclingDocument(name="formulas")
    image = Image.new("RGB", (100, 100), "blue")
    doc.add_page(
        page_no=1,
        size=Size(width=100, height=100),
        image=ImageRef.from_pil(image, dpi=72),
    )
    doc.add_text(
        label=DocItemLabel.FORMULA,
        text="",
        orig="x+y",
        prov=ProvenanceItem(
            page_no=1,
            charspan=(0, 3),
            bbox=BoundingBox(l=10, t=10, r=50, b=40, coord_origin=CoordOrigin.TOPLEFT),
        ),
    )
    doc.add_text(label=DocItemLabel.FORMULA, text="x=y")
    for _ in range(2):
        doc.add_picture(image=ImageRef.from_pil(image, dpi=72))
    document(doc, tmp_path, 1000, max_text_bytes=262144)
    markdown = (tmp_path / "README.md").read_text()
    assert "![Formula](formula-1.png)" in markdown
    assert "formula-not-decoded" not in markdown
    assert "$$x=y$$" in markdown
    assert Image.open(tmp_path / "formula-1.png").size == (40, 30)
    assert len(list(tmp_path.glob("image-*.png"))) == 1
    assert markdown.count("image-1.png") == 2


def test_table_parts_preserve_utf8_multiline_rows_and_all_links(tmp_path: Path) -> None:
    from docling_core.types.doc.items.table.table_data import TableCell, TableData

    doc = DoclingDocument(name="survey")
    rows = [
        ["Địa điểm", "Ghi chú"],
        *[[str(i), 'Nội dung, "trích dẫn"\nxuống dòng'] for i in range(12)],
    ]
    doc.add_table(
        data=TableData(
            num_rows=len(rows),
            num_cols=2,
            table_cells=[
                TableCell(
                    text=value,
                    start_row_offset_idx=i,
                    end_row_offset_idx=i + 1,
                    start_col_offset_idx=j,
                    end_col_offset_idx=j + 1,
                )
                for i, row in enumerate(rows)
                for j, value in enumerate(row)
            ],
        )
    )
    document(doc, tmp_path, 1000, max_text_bytes=400)
    markdown = "\n".join(path.read_text() for path in sorted(tmp_path.glob("*.md")))
    targets = list(dict.fromkeys(re.findall(r"\]\(([^)]+\.csv)\)", markdown)))
    assert len(targets) > 1
    actual: list[list[str]] = []
    for name in targets:
        path = tmp_path / name
        assert path.stat().st_size <= 400
        with path.open(newline="") as stream:
            actual.extend(csv.reader(stream))
    assert actual == rows
    assert "Column labels and table context" in markdown
    from letfs_ingest.export import write_rows

    with pytest.raises(ValueError, match="row exceeds"):
        write_rows(rows, tmp_path / "too-small.csv", 5)


def test_long_prose_splits_between_paragraphs_and_keeps_structures(
    tmp_path: Path,
) -> None:
    from docling_core.types.doc.items.table.table_data import RichTableCell, TableData

    doc = DoclingDocument(name="prose")
    for number in range(8):
        doc.add_text(
            label=DocItemLabel.TEXT,
            text=f"Paragraph {number}: " + "complete content " * 10,
        )
    table = doc.add_table(data=TableData(num_rows=1, num_cols=1, table_cells=[]))
    cell = doc.add_group(parent=table)
    for number in range(2):
        doc.add_text(
            label=DocItemLabel.TEXT,
            text=f"Rich cell paragraph {number}: " + "retained content " * 20,
            parent=cell,
        )
    doc.add_table_cell(
        table,
        RichTableCell(
            text="",
            ref=cell.get_ref(),
            start_row_offset_idx=0,
            end_row_offset_idx=1,
            start_col_offset_idx=0,
            end_col_offset_idx=1,
        ),
    )
    group = doc.add_list_group()
    doc.add_list_item(text="First list entry", parent=group)
    doc.add_list_item(text="Second list entry", parent=group)
    inline = doc.add_inline_group()
    for number in range(2):
        doc.add_text(
            label=DocItemLabel.TEXT,
            text=f"Inline run {number} " + "kept together " * 20,
            parent=inline,
        )
    doc.add_text(label=DocItemLabel.TEXT, text="Final paragraph retained.")
    document(doc, tmp_path, 100, max_text_bytes=262144)
    outputs = list(tmp_path.rglob("*.md"))
    assert len(outputs) > 1
    combined = "\n".join(p.read_text() for p in [*outputs, *tmp_path.rglob("*.csv")])
    for item in doc.texts:
        assert combined.count(item.text.rstrip()) == 1
    assert len(list(tmp_path.rglob("*.csv"))) == 1


def test_empty_structure_is_removed_without_editing_code_or_inline_text(
    tmp_path: Path,
) -> None:
    doc = DoclingDocument(name="cleanup")
    doc.add_heading(" ")
    group = doc.add_list_group()
    doc.add_list_item(text=" ", parent=group)
    doc.add_list_item(text="Kept entry", parent=group)
    heading = doc.add_heading("")
    inline = doc.add_inline_group(parent=heading)
    doc.add_text(label=DocItemLabel.TEXT, text="Inline heading retained", parent=inline)
    heading = doc.add_heading("")
    for number in range(2):
        inline = doc.add_inline_group(parent=heading)
        doc.add_text(
            label=DocItemLabel.TEXT, text=f"Nested paragraph {number}", parent=inline
        )
        doc.add_text(label=DocItemLabel.TEXT, text="", parent=heading)
    doc.add_list_item(text="", enumerated=True, marker="7.", parent=group)
    doc.add_text(label=DocItemLabel.CHECKBOX_SELECTED, text="")
    doc.add_text(label=DocItemLabel.CHECKBOX_UNSELECTED, text="")
    code = "#\n-\nprint('retained')"
    doc.add_code(text=code)
    document(doc, tmp_path, 1000, max_text_bytes=262144)
    markdown = (tmp_path / "README.md").read_text()
    assert code in markdown
    assert "## Inline heading retained" in markdown
    assert all(f"Nested paragraph {number}" in markdown for number in range(2))
    assert "- Kept entry" in markdown
    assert not re.search(r"^[ \t]*[-*+][ \t]*$", markdown.split("```")[0], re.M)
    assert "7." in markdown and "[x]" in markdown and "[ ]" in markdown
    assert not re.search(r"^#{1,6}\s*$", markdown.split("```")[0], re.M)


def test_spreadsheet_parts_have_actual_ranges_and_context(
    tmp_path: Path, config: Config
) -> None:
    from letfs_ingest.export import spreadsheets

    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet.title = "Survey"
    rows = [["Date", "Result"], *[[f"Period {i}", "12.5%"] for i in range(8)]]
    for row in rows:
        sheet.append(row)
    source = tmp_path / "survey.xlsx"
    workbook.save(source)
    from letfs_ingest.convert import converter

    doc = converter(config).convert(source).document
    output = tmp_path / "output"
    output.mkdir()
    spreadsheets(doc, source, output, max_text_bytes=240, split_tokens=20)
    markdown = "\n".join(p.read_text() for p in sorted(output.glob("*.md")))
    actual = exported_tables(output)
    assert [row for table in actual for row in table] == rows
    assert "columns A-B" in markdown
    assert all(p.stat().st_size <= 240 for p in output.glob("*.csv"))


def test_conversion_rejects_text_limit_before_publish(
    tmp_path: Path, config: Config
) -> None:
    from docx import Document

    word = Document()
    word.add_paragraph("Retained content " * 100)
    source = tmp_path / "large.docx"
    word.save(str(source))
    output = tmp_path / "output"
    output.mkdir()
    config["services"]["letfs"]["max_text_bytes"] = 100
    with pytest.raises(InvalidDocument, match="artifact text exceeds"):
        convert(
            source,
            output,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            config,
        )


def test_spreadsheet_outside_tables_keeps_cached_and_array_formula(
    tmp_path: Path,
) -> None:
    from xml.etree import ElementTree
    from zipfile import ZipFile

    from letfs_ingest.export import spreadsheets
    from openpyxl.worksheet.formula import ArrayFormula

    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet["B2"] = "=1-1"
    sheet["D4"] = ArrayFormula(ref="D4", text="=1+2")
    source = tmp_path / "cached.xlsx"
    workbook.save(source)
    with ZipFile(source) as archive:
        entries = {name: archive.read(name) for name in archive.namelist()}
    ns = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    xml = ElementTree.fromstring(entries["xl/worksheets/sheet1.xml"])
    for cell in xml.findall(".//x:c", ns):
        value = cell.find("x:v", ns)
        assert value is not None
        value.text = "0" if cell.get("r") == "B2" else "3"
    entries["xl/worksheets/sheet1.xml"] = ElementTree.tostring(xml)
    with ZipFile(source, "w") as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    spreadsheets(DoclingDocument(name="cached"), source, tmp_path, 262144)
    markdown = (tmp_path / "README.md").read_text()
    assert "B2: 0 (formula: =1-1)" in markdown
    assert "D4: 3 (formula: =1+2)" in markdown
    assert "object at" not in markdown


def test_nested_tables_and_rich_images_remain_reachable(tmp_path: Path) -> None:
    from docling_core.types.doc.items.table.table_data import (
        RichTableCell,
        TableCell,
        TableData,
    )

    doc = DoclingDocument(name="nested")
    outer = doc.add_table(data=TableData(num_rows=1, num_cols=1, table_cells=[]))
    group = doc.add_group(parent=outer)
    doc.add_text(label=DocItemLabel.TEXT, text="Important cell context", parent=group)
    doc.add_picture(
        parent=group, image=ImageRef.from_pil(Image.new("RGB", (8, 8), "blue"), dpi=72)
    )
    doc.add_table(
        parent=group,
        data=TableData(
            num_rows=1,
            num_cols=1,
            table_cells=[
                TableCell(
                    text="Nested value",
                    start_row_offset_idx=0,
                    end_row_offset_idx=1,
                    start_col_offset_idx=0,
                    end_col_offset_idx=1,
                )
            ],
        ),
    )
    doc.add_table_cell(
        outer,
        RichTableCell(
            text="",
            ref=group.get_ref(),
            start_row_offset_idx=0,
            end_row_offset_idx=1,
            start_col_offset_idx=0,
            end_col_offset_idx=1,
        ),
    )
    document(doc, tmp_path, 4096, 262144)
    combined = "\n".join(
        p.read_text() for p in tmp_path.iterdir() if p.suffix in {".md", ".csv"}
    )
    assert "Important cell context" in combined and "Nested value" in combined
    assert "data:image" not in combined
    for target in re.findall(r"\]\(([^)]+)\)", combined):
        assert (tmp_path / target).is_file(), target
    from letfs_ingest.naming import rewrite_artifact_links

    mapping = {
        p.name: ("renamed-" + p.name if p.name != "README.md" else p.name)
        for p in tmp_path.iterdir()
    }
    for path in tmp_path.glob("*.md"):
        enriched = rewrite_artifact_links(path.read_text(), path.name, mapping)
        assert "renamed-image-1.png" in enriched
