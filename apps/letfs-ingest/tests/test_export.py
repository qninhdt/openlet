import csv
import re
from pathlib import Path
from typing import cast

import pytest
from docling_core.types.doc.common.reference import ImageRef
from docling_core.types.doc.document import DoclingDocument
from docling_core.types.doc.labels import DocItemLabel
from letfs_ingest.convert import InvalidDocument, convert, preflight
from letfs_ingest.export import document
from openlet_sdk.config import Config
from openpyxl import Workbook
from PIL import Image


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
    source = tmp_path / "report.xlsx"
    workbook.save(source)
    output = tmp_path / "artifacts"
    output.mkdir()
    convert(
        source,
        output,
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        config,
    )
    assert "Sales" in (output / "README.md").read_text()
    assert "D5: Forecast note" in (output / "sheet-1/README.md").read_text()
    assert "D7: =1+2" in (output / "sheet-1/README.md").read_text()
    with (output / "sheet-1/table-1.csv").open() as stream:
        assert list(csv.reader(stream)) == [
            ["Quarter", "Revenue"],
            ["Q1", "100"],
            ["Q2", "250"],
        ]
    assert "Research" in (output / "sheet-1/table-2.csv").read_text()
    assert "Research" not in (output / "sheet-1/README.md").read_text()
    assert (output / "sheet-2/README.md").read_text() == "# Empty"
    assert list(output.rglob("*.png"))


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
    document(doc, tmp_path, minimum_tokens=20, split_tokens=100)
    markdown = list(tmp_path.rglob("*.md"))
    combined = "\n".join(path.read_text() for path in markdown)
    for number in range(3):
        assert combined.count(f"Evidence {number}:") == 1
    for path in markdown:
        for target in re.findall(r"\]\(([^)]+)\)", path.read_text()):
            assert (path.parent / target).is_file(), (path, target)
    assert list(tmp_path.rglob("*.png"))


@pytest.mark.parametrize(
    "threshold,files,folders", [(10000, 1, 0), (400, 3, 0), (50, 7, 2)]
)
def test_document_layout_preserves_nested_sections_once(
    tmp_path: Path, threshold: int, files: int, folders: int
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
    document(doc, tmp_path, 10, threshold)
    outputs = list(tmp_path.rglob("*.md"))
    assert len(outputs) == files
    assert sum(path.is_dir() for path in tmp_path.iterdir()) == folders
    combined = "\n".join(path.read_text() for path in outputs)
    for item in doc.texts:
        assert combined.count(item.text) == 1


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
        < markdown.index("[Table](table-1.csv)")
        < markdown.index("After table.")
    )
    assert (
        "Visible controlled content retained." in (output / "table-1.csv").read_text()
    )
    assert "controlled content" not in markdown


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
