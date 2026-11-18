import re
from pathlib import Path
from typing import cast

import pytest
from letfs_ingest.convert import InvalidDocument, convert, preflight
from openlet_sdk.config import Config
from openpyxl import Workbook
from PIL import Image


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
    assert markdown.index("Compatibility text survives") < markdown.index(
        "Untitled second slide"
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
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
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


def test_conversion_rejects_text_limit_before_publish(
    tmp_path: Path, config: Config
) -> None:
    from pptx import Presentation

    slides = Presentation()
    slide = slides.slides.add_slide(slides.slide_layouts[5])
    assert slide.shapes.title is not None
    slide.shapes.title.text = "Retained content " * 100
    source = tmp_path / "large.pptx"
    slides.save(str(source))
    output = tmp_path / "output"
    output.mkdir()
    config["services"]["letfs"]["max_text_bytes"] = 100
    with pytest.raises(InvalidDocument, match="artifact text exceeds"):
        convert(
            source,
            output,
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            config,
        )
