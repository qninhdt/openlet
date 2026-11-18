from typing import TYPE_CHECKING

from openlet_sdk.config import Config

if TYPE_CHECKING:
    from docling.document_converter import DocumentConverter
    from docling_core.types.doc.document import DoclingDocument
import argparse
import logging
import os
import sys
import warnings
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from openlet_sdk.config import load

PDF = "application/pdf"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
REMOTE_MEDIA = {PDF, DOCX}
MEDIA_SUFFIXES = {
    PDF: ".pdf",
    DOCX: ".docx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
}


class InvalidDocument(ValueError):
    pass


def preflight(source: Path, media: str, config: Config) -> None:
    limits = config["services"]["letfs_ingest"]["cpu"]["limits"]
    if source.stat().st_size > config["services"]["letfs"]["max_blob_bytes"]:
        raise InvalidDocument("input exceeds blob limit")
    if media == PDF:
        import pypdfium2  # pyright: ignore[reportMissingTypeStubs]  # Upstream package does not publish type stubs.

        try:
            pdf = pypdfium2.PdfDocument(source)
        except pypdfium2.PdfiumError as error:
            raise InvalidDocument("invalid PDF") from error
        with pdf:
            if len(pdf) > limits["max_pages"]:
                raise InvalidDocument("PDF exceeds page limit")
            for page in pdf:
                try:
                    width, height = page.get_size()
                    if width * height * 9 > limits["max_page_pixels"]:
                        raise InvalidDocument("PDF page exceeds pixel limit")
                finally:
                    page.close()
    else:
        try:
            with ZipFile(source) as archive:
                if (
                    sum(entry.file_size for entry in archive.infolist())
                    > limits["max_office_expanded_bytes"]
                ):
                    raise InvalidDocument("Office document exceeds expanded size limit")
        except BadZipFile as error:
            raise InvalidDocument("invalid Office archive") from error
        if media.endswith("spreadsheetml.sheet"):
            from openpyxl import load_workbook

            workbook = load_workbook(source, read_only=True)
            try:
                if (
                    len(workbook.worksheets) > limits["max_sheets"]
                    or sum(
                        sheet.max_row * sheet.max_column
                        for sheet in workbook.worksheets
                    )
                    > limits["max_spreadsheet_cells"]
                ):
                    raise InvalidDocument("spreadsheet exceeds sheet/cell limit")
            finally:
                workbook.close()


def converter() -> DocumentConverter:
    from docling.datamodel.base_models import InputFormat
    from docling.document_converter import DocumentConverter, PowerpointFormatOption

    from .office import Powerpoint

    return DocumentConverter(
        allowed_formats=[InputFormat.PPTX, InputFormat.XLSX],
        format_options={
            InputFormat.PPTX: PowerpointFormatOption(backend=Powerpoint),
        },
    )


def spreadsheet_details(source: Path, document: "DoclingDocument") -> None:
    from contextlib import closing

    from docling_core.types.doc.labels import DocItemLabel, GroupLabel
    from openpyxl import load_workbook
    from openpyxl.cell.read_only import ReadOnlyCell

    with (
        closing(load_workbook(source, read_only=True, keep_links=False)) as formulas,
        closing(
            load_workbook(source, read_only=True, keep_links=False, data_only=True)
        ) as values,
    ):
        sheets = {sheet.title: sheet for sheet in formulas.worksheets}
        cached = {sheet.title: sheet for sheet in values.worksheets}
        for group in document.groups:
            if group.label != GroupLabel.SHEET or group.name not in sheets:
                continue
            sheet = sheets[group.name]
            if sheet.sheet_state != "visible":
                continue
            document.add_heading(group.name, level=2, parent=group)
            group.children.insert(0, group.children.pop())
            for row, value_row in zip(
                sheet.rows, cached[group.name].values, strict=True
            ):
                for cell, value in zip(row, value_row, strict=True):
                    if not isinstance(cell, ReadOnlyCell) or cell.data_type != "f":
                        continue
                    formula = (
                        cell.value
                        if isinstance(cell.value, str)
                        else getattr(cell.value, "text", None)
                    )
                    text = f"{cell.coordinate}: {formula or '[formula]'}"
                    if value is not None:
                        text += f" (cached value: {value})"
                    document.add_text(DocItemLabel.PARAGRAPH, text, parent=group)


def convert(
    source: Path,
    output: Path,
    media: str,
    config: Config,
    *,
    source_name: str | None = None,
) -> None:
    from docling.datamodel.base_models import ConversionStatus
    from docling_core.types.doc.base import ImageRefMode
    from PIL import Image

    from .layout import write_markdown
    from .tables import externalize_tables

    settings = config["services"]["letfs_ingest"]["cpu"]
    limits = settings["limits"]
    preflight(source, media, config)
    Image.MAX_IMAGE_PIXELS = limits["max_page_pixels"]
    warnings.simplefilter("error", Image.DecompressionBombWarning)
    result = converter().convert(
        source,
        raises_on_error=False,
        max_num_pages=limits["max_pages"],
        max_file_size=config["services"]["letfs"]["max_blob_bytes"],
    )
    if result.status != ConversionStatus.SUCCESS:
        raise InvalidDocument("document conversion incomplete")
    spreadsheet = media.endswith("spreadsheetml.sheet")
    if spreadsheet:
        spreadsheet_details(source, result.document)
    readme = output / "README.md"
    result.document.save_as_markdown(
        readme,
        artifacts_dir=Path("."),
        image_mode=ImageRefMode.REFERENCED,
        traverse_pictures=True,
        include_picture_classification=False,
    )
    body = readme.read_text()
    if source_name and spreadsheet:
        body = f"# {' '.join(Path(source_name).stem.split())}\n\n{body}"
    max_text = config["services"]["letfs"]["max_text_bytes"]
    try:
        body = externalize_tables(body, output, settings["split_tokens"], max_text)
        write_markdown(body, output, settings["split_tokens"], max_text)
    except ValueError as error:
        raise InvalidDocument(str(error)) from error
    validate_output(output, config)


def validate_output(output: Path, config: Config) -> None:
    limits = config["services"]["letfs_ingest"]["cpu"]["limits"]
    entries = list(output.rglob("*"))
    texts = [
        path for path in entries if path.suffix in {".md", ".csv", ".json", ".txt"}
    ]
    if any(
        path.stat().st_size > config["services"]["letfs"]["max_text_bytes"]
        for path in texts
    ):
        raise InvalidDocument("artifact text exceeds limit")
    if (
        sum(path.stat().st_size for path in texts)
        > config["services"]["letfs"]["processing"]["max_manifest_text_bytes"]
    ):
        raise InvalidDocument("artifact manifest exceeds limit")
    if (
        len(entries) > config["services"]["letfs"]["processing"]["max_artifacts"]
        or sum(path.stat().st_size for path in entries if path.is_file())
        > limits["max_output_bytes"]
    ):
        raise InvalidDocument("parser output exceeds budget")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("media_type")
    parser.add_argument("--source-name")
    args = parser.parse_args()
    logging.basicConfig(level=logging.ERROR)
    try:
        convert(
            args.source,
            args.output,
            args.media_type,
            load(),
            source_name=args.source_name,
        )
    except InvalidDocument as error:
        print(str(error), file=sys.stderr)
        sys.exit(os.EX_DATAERR)
