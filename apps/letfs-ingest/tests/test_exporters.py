import csv
import os
import re
from pathlib import Path

import pytest

from letfs_ingest.convert_child import ResourceLimit, check_outputs, convert
from letfs_ingest.exporters import markdown, slug

FIXTURES = Path(__file__).parent / "fixtures"


def test_names_and_output_limits(tmp_path):
    assert slug("../Hello / Việt: report?") == "hello-việt-report"
    assert slug("...") == "untitled"
    (tmp_path / "file").write_bytes(b"1234")
    with pytest.raises(ResourceLimit):
        check_outputs(tmp_path, 1, 3)
    (tmp_path / "directory").mkdir()
    with pytest.raises(ResourceLimit):
        check_outputs(tmp_path, 1, 10)
    (tmp_path / "link").symlink_to("file")
    with pytest.raises(ValueError):
        check_outputs(tmp_path, 10, 10)


def test_section_boundaries_preserve_picture_children(tmp_path, monkeypatch):
    monkeypatch.setenv("MIN_LEAF_TOKENS", "1")
    monkeypatch.setenv("SPLIT_TOKENS", "1")
    from docling_core.types.doc import DocItemLabel, DoclingDocument

    document = DoclingDocument(name="nested-picture")
    document.add_heading("First")
    picture = document.add_picture()
    document.add_text(
        label=DocItemLabel.TEXT, text="Text inside picture.", parent=picture
    )
    document.add_heading("Second")
    document.add_text(label=DocItemLabel.TEXT, text="Closing paragraph.")
    markdown(document, tmp_path, "pdf")
    first = (tmp_path / "1-untitled.md").read_text()
    assert "Text inside picture." in first
    assert "Second" not in first
    assert (tmp_path / "2-untitled.md").read_text() == (
        "## Second\n\nClosing paragraph."
    )


def test_section_export_writes_each_picture_once(tmp_path, monkeypatch):
    from docling_core.types.doc import DocItemLabel, DoclingDocument, ImageRef
    from PIL import Image

    document = DoclingDocument(name="illustrated-sections")
    for number in range(3):
        document.add_heading(f"Section {number}")
        document.add_text(label=DocItemLabel.TEXT, text=f"Body {number}.")
        document.add_picture(
            image=ImageRef.from_pil(Image.new("RGB", (8, 8), (number, 20, 30)), 72)
        )
    monkeypatch.setenv("MIN_LEAF_TOKENS", "1")
    monkeypatch.setenv("SPLIT_TOKENS", "1")
    original_save = Image.Image.save
    writes = []

    def save(image, target, *args, **kwargs):
        writes.append(target)
        return original_save(image, target, *args, **kwargs)

    monkeypatch.setattr(Image.Image, "save", save)
    markdown(document, tmp_path, "docx")
    assert len(writes) == 3
    for number, path in enumerate(sorted(tmp_path.glob("*-untitled.md"))):
        text = path.read_text()
        assert f"Body {number}." in text
        targets = re.findall(r"!\[[^\]]*\]\(([^)]+)\)", text)
        assert len(targets) == 1
        assert not Path(targets[0]).is_absolute()
        assert (tmp_path / targets[0]).is_file()


@pytest.mark.parser
@pytest.mark.parametrize("wrapper", ["sdt", "ins"])
def test_word_wrapped_runs_preserve_visible_table_and_body_text(tmp_path, wrapper):
    from docx import Document
    from docx.oxml import OxmlElement

    document = Document()
    paragraph = document.add_paragraph("Controlled body text.")
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 1).text = "Program"
    table.cell(1, 0).text = "Details"
    table.cell(1, 1).text = "Retained value"
    cell = table.cell(0, 0)
    cell.text = "Global Design Challenge"
    for target, prefix in ((paragraph, "Controlled"), (cell.paragraphs[0], "G")):
        run = target.runs[0]
        suffix = run.text[len(prefix) :]
        run.text = prefix
        control = OxmlElement(f"w:{wrapper}")
        content = OxmlElement("w:sdtContent") if wrapper == "sdt" else control
        if wrapper == "sdt":
            control.append(content)
        target._p.replace(run._r, control)
        content.append(run._r)
        target.add_run(suffix)
    source = tmp_path / "controls.docx"
    document.save(source)
    output = tmp_path / "output"
    output.mkdir()
    convert(source, output, "docx", Path("/unused-models"))
    text = "\n".join(path.read_text() for path in output.glob("*.md"))
    assert "Controlled body text." in text
    assert "Global Design Challenge" not in text
    assert "Global Design Challenge" in (output / "untitled-1.csv").read_text()


@pytest.mark.parser
def test_powerpoint_compatibility_preserves_text_math_and_fallback_picture(tmp_path):
    from copy import deepcopy

    from lxml import etree
    from PIL import Image
    from pptx import Presentation
    from pptx.util import Inches

    namespaces = {
        "mc": "http://schemas.openxmlformats.org/markup-compatibility/2006",
        "a14": "http://schemas.microsoft.com/office/drawing/2010/main",
        "m": "http://schemas.openxmlformats.org/officeDocument/2006/math",
        "p14": "http://schemas.microsoft.com/office/powerpoint/2010/main",
    }
    presentation = Presentation(FIXTURES / "tiny.pptx")
    slide = presentation.slides[0]
    shape = slide.shapes.add_textbox(Inches(1), Inches(2), Inches(5), Inches(1))
    shape.text = "Compatible body text "
    paragraph = shape.text_frame.paragraphs[0]._p
    math = etree.SubElement(paragraph, f"{{{namespaces['a14']}}}m")
    equation = etree.SubElement(math, f"{{{namespaces['m']}}}oMath")
    run = etree.SubElement(equation, f"{{{namespaces['m']}}}r")
    etree.SubElement(run, f"{{{namespaces['m']}}}t").text = "x"

    def wrap(element, requires, use_choice):
        parent = element.getparent()
        alternate = etree.Element(
            f"{{{namespaces['mc']}}}AlternateContent", nsmap=namespaces
        )
        choice = etree.SubElement(
            alternate, f"{{{namespaces['mc']}}}Choice", Requires=requires
        )
        fallback = etree.SubElement(alternate, f"{{{namespaces['mc']}}}Fallback")
        (choice if use_choice else fallback).append(deepcopy(element))
        parent.replace(element, alternate)

    wrap(shape._element, "a14", True)
    image = tmp_path / "ink.png"
    Image.new("RGB", (16, 12), "blue").save(image)
    picture = slide.shapes.add_picture(str(image), Inches(1), Inches(3))
    wrap(picture._element, "p14", False)
    source = tmp_path / "compatible.pptx"
    presentation.save(source)
    output = tmp_path / "output"
    output.mkdir()
    convert(source, output, "pptx", Path("/unused-models"))
    content = (output / "README.md").read_text()
    assert "# Summary\n\n- Done slides." in content
    assert "<!-- slide 2 -->" in content
    assert "Compatible body text" in content
    assert "$x$" in content
    targets = re.findall(r"!\[[^\]]*\]\(([^)]+)\)", content)
    assert len(targets) == 1
    with Image.open(output / targets[0]) as extracted:
        assert extracted.size == (16, 12)
        assert extracted.getpixel((0, 0)) == (0, 0, 255)


@pytest.mark.parser
@pytest.mark.parametrize("kind", ["pdf", "docx", "pptx", "xlsx"])
def test_real_parser_exports_preserve_content(kind, tmp_path, monkeypatch):
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setenv("TRANSFORMERS_OFFLINE", "1")
    models = Path(os.environ["DOCLING_MODELS_PATH"])
    convert(FIXTURES / f"tiny.{kind}", tmp_path, kind, models)
    files = sorted(
        p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file()
    )
    assert all(not p.endswith(".json") for p in files)
    if kind == "docx":
        assert files == ["README.md", "untitled-1.csv"]
        content = (tmp_path / "README.md").read_text()
        assert content.startswith("Preamble\n\n## Introduction")
        assert "Hello document." in content
        assert "### Details\n\nNested detail." in content
        assert "## Conclusion\n\nDone." in content
        assert "[Table](untitled-1.csv)" in content
        assert "Apple" not in content
        assert "Apple" in (tmp_path / "untitled-1.csv").read_text()
    elif kind == "pptx":
        assert files == ["README.md"]
        content = (tmp_path / "README.md").read_text()
        assert "<!-- slide 1 -->\n\n# Overview\n\n- Hello slides." in content
        assert "<!-- slide 2 -->\n\n# Summary\n\n- Done slides." in content
    elif kind == "xlsx":
        assert files == [
            "1-untitled/README.md",
            "1-untitled/untitled-1.csv",
            "2-untitled/README.md",
            "README.md",
        ]
        content = (tmp_path / "1-untitled/README.md").read_text()
        assert "isolated" in content and "formula" in content and "=1+2" in content
        assert "Apple" not in content
        assert "A1:B2" in content
        assert (tmp_path / "2-untitled/README.md").read_text() == "# Empty"
        with (tmp_path / "1-untitled/untitled-1.csv").open(newline="") as file:
            assert list(csv.reader(file)) == [["Item", "Count"], ["Apple", "3"]]
    else:
        assert files == ["README.md"]
        content = (tmp_path / "README.md").read_text()
        assert "Introduction" in content and "Hello PDF." in content


@pytest.mark.parser
def test_embedded_image_is_extracted_and_referenced(tmp_path, monkeypatch):
    from PIL import Image

    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    models = Path(os.environ["DOCLING_MODELS_PATH"])
    convert(FIXTURES / "image.docx", tmp_path, "docx", models)
    markdown = (tmp_path / "README.md").read_text()
    assert "Embedded image remains available." in markdown
    images = list(tmp_path.glob("untitled-*.png"))
    assert len(images) == 1
    targets = re.findall(r"!\[[^\]]*\]\(([^)]+)\)", markdown)
    assert len(targets) == 1
    target = Path(targets[0])
    assert not target.is_absolute()
    assert (tmp_path / target).resolve() == images[0].resolve()
    with Image.open(FIXTURES / "image.png") as source, Image.open(images[0]) as output:
        assert output.size == source.size
        assert output.convert("RGB").tobytes() == source.tobytes()


@pytest.mark.parser
def test_scanned_pdf_exports_ocr_text(tmp_path, monkeypatch):
    import pypdfium2
    from PIL import Image, ImageDraw, ImageFont

    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setenv("TRANSFORMERS_OFFLINE", "1")
    source = tmp_path / "scan.pdf"
    with Image.new("RGB", (1400, 400), "white") as image:
        ImageDraw.Draw(image).text(
            (60, 120),
            "Openlet scanned document 4826",
            font=ImageFont.load_default(size=56),
            fill="black",
        )
        image.save(source, "PDF", resolution=150)
    with pypdfium2.PdfDocument(source) as pdf:
        page = pdf[0]
        try:
            text = page.get_textpage()
            try:
                assert text.get_text_range().strip() == ""
            finally:
                text.close()
        finally:
            page.close()
    output = tmp_path / "output"
    output.mkdir()
    convert(source, output, "pdf", Path(os.environ["DOCLING_MODELS_PATH"]))
    content = "\n".join(p.read_text() for p in output.glob("*.md")).lower()
    assert "openlet scanned document 4826" in content


@pytest.mark.parser
def test_excel_retains_outside_text_formula_and_image(tmp_path):
    from openpyxl import Workbook
    from openpyxl.drawing.image import Image

    book = Workbook()
    sheet = book.active
    sheet.title = "Instructions and data"
    sheet["A1"] = "Read these instructions."
    for row in [["Item", "Count"], ["Apple", 3]]:
        sheet.append(row)
    sheet["H8"] = "=1+2"
    sheet.add_image(Image(FIXTURES / "image.png"), "J10")
    source = tmp_path / "image.xlsx"
    book.save(source)
    output = tmp_path / "output"
    output.mkdir()
    convert(source, output, "xlsx", Path("/unused-models"))
    assert (output / "1-untitled/untitled-1.png").is_file()
    text = (output / "1-untitled/README.md").read_text()
    assert "=1+2" in text
    assert "![Image](untitled-1.png)" in text
