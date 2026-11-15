from pathlib import Path

import pytest
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import ConvertPipelineOptions
from docling_core.types.doc.common.reference import ImageRef
from docling_core.types.doc.document import DoclingDocument
from docling_core.types.doc.items.picture.meta import (
    PictureClassificationMetaField,
    PictureClassificationPrediction,
    PictureMeta,
)
from docling_core.types.doc.items.picture.picture import PictureItem
from docling_core.types.doc.items.table.table_data import RichTableCell, TableData
from docling_core.types.doc.labels import DocItemLabel, GroupLabel
from letfs_ingest.convert import converter
from letfs_ingest.export import document, spreadsheets
from openlet_sdk.config import Config
from openpyxl import Workbook
from PIL import Image


def classify(item: PictureItem, label: str, confidence: float | None) -> None:
    item.meta = PictureMeta(
        classification=PictureClassificationMetaField(
            predictions=[
                PictureClassificationPrediction(
                    class_name=label, confidence=confidence, created_by="test"
                )
            ]
        )
    )


@pytest.mark.parametrize(
    "label,confidence,caption,retained",
    [
        ("logo", 0.9, False, False),
        ("logo", 0.89, False, True),
        ("logo", 0.99, True, True),
        ("icon", 0.999, False, True),
        ("line_chart", 0.99, False, True),
        ("logo", None, False, True),
        (None, 0, False, True),
    ],
)
def test_export_only_omits_confident_uncaptioned_logos(
    tmp_path: Path,
    label: str | None,
    confidence: float | None,
    caption: bool,
    retained: bool,
) -> None:
    doc = DoclingDocument(name="report")
    doc.add_text(label=DocItemLabel.TEXT, text="Important surrounding content")
    item = doc.add_picture(
        image=ImageRef.from_pil(Image.new("RGB", (16, 16), "red"), dpi=72)
    )
    if label is not None:
        classify(item, label, confidence)
    if caption:
        item.captions = [
            doc.add_text(
                label=DocItemLabel.CAPTION, text="Meaningful example"
            ).get_ref()
        ]
    document(doc, tmp_path, 4096, 262144)
    assert bool(list(tmp_path.rglob("*.png"))) == retained
    text = (tmp_path / "README.md").read_text()
    assert "Important surrounding content" in text
    assert ("![Image](" in text) == retained
    if caption:
        assert "Meaningful example" in text


def test_rich_table_filter_preserves_text_and_uses_highest_prediction(
    tmp_path: Path,
) -> None:
    doc = DoclingDocument(name="rich content")
    table = doc.add_table(data=TableData(num_rows=1, num_cols=1, table_cells=[]))
    cell = doc.add_group(parent=table)
    doc.add_text(label=DocItemLabel.TEXT, text="Cell context retained", parent=cell)
    item = doc.add_picture(
        parent=cell,
        image=ImageRef.from_pil(Image.new("RGB", (16, 16), "red"), dpi=72),
    )
    classify(item, "logo", 0.99)
    assert item.meta is not None and item.meta.classification is not None
    item.meta.classification.predictions.insert(
        0,
        PictureClassificationPrediction(
            class_name="photograph", confidence=0.01, created_by="test"
        ),
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
    document(doc, tmp_path, 4096, 262144)
    assert not list(tmp_path.rglob("*.png"))
    text = (tmp_path / "README.md").read_text()
    assert "Cell context retained" in text
    assert not list(tmp_path.glob("*.csv"))


def test_spreadsheet_applies_the_same_filter(tmp_path: Path) -> None:
    workbook = Workbook()
    source = tmp_path / "input.xlsx"
    workbook.save(source)
    doc = DoclingDocument(name="workbook")
    sheet = doc.add_group(label=GroupLabel.SHEET, name="Sheet")
    for color, label in [("red", "logo"), ("green", "icon")]:
        item = doc.add_picture(
            parent=sheet,
            image=ImageRef.from_pil(Image.new("RGB", (16, 16), color), dpi=72),
        )
        classify(item, label, 0.99)
    spreadsheets(doc, source, tmp_path, 262144)
    images = list(tmp_path.rglob("*.png"))
    assert len(images) == 1
    with Image.open(images[0]) as retained:
        assert retained.getpixel((0, 0)) == (0, 128, 0)
    text = (tmp_path / "README.md").read_text()
    assert text.count("![Image](") == 1
    assert images[0].name in text


def test_all_formats_classify_pictures_on_cpu(config: Config) -> None:
    engine = converter(config)
    for format in (
        InputFormat.PDF,
        InputFormat.DOCX,
        InputFormat.XLSX,
        InputFormat.PPTX,
    ):
        options = engine.format_to_options[format].pipeline_options
        assert isinstance(options, ConvertPipelineOptions)
        assert options.do_picture_classification
        assert options.accelerator_options.device == "cpu"
        assert (
            str(options.artifacts_path)
            == config["services"]["letfs_ingest"]["cpu"]["docling_models_path"]
        )
