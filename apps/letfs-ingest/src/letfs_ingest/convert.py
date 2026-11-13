from typing import TYPE_CHECKING

from openlet_sdk.config import Config

if TYPE_CHECKING:
    from docling.document_converter import DocumentConverter
import argparse
import logging
import os
import sys
import warnings
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from openlet_sdk.config import load

MEDIA_SUFFIXES = {
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
}


class InvalidDocument(ValueError):
    pass


def preflight(source: Path, media: str, config: Config) -> None:
    limits = config["services"]["letfs_ingest"]["cpu"]["limits"]
    if source.stat().st_size > config["services"]["letfs"]["max_blob_bytes"]:
        raise InvalidDocument("input exceeds blob limit")
    if media == "application/pdf":
        import pypdfium2

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
                if sum(entry.file_size for entry in archive.infolist()) > limits["max_office_expanded_bytes"]:
                    raise InvalidDocument("Office document exceeds expanded size limit")
        except BadZipFile as error:
            raise InvalidDocument("invalid Office archive") from error
        if media.endswith("spreadsheetml.sheet"):
            from openpyxl import load_workbook

            workbook = load_workbook(source, read_only=True)
            try:
                if len(workbook.worksheets) > limits["max_sheets"] or sum(
                    sheet.max_row * sheet.max_column for sheet in workbook.worksheets
                ) > limits["max_spreadsheet_cells"]:
                    raise InvalidDocument("spreadsheet exceeds sheet/cell limit")
            finally:
                workbook.close()


def converter(config: Config) -> DocumentConverter:
    from docling.datamodel.accelerator_options import AcceleratorOptions
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions, RapidOcrOptions
    from docling.document_converter import (
        DocumentConverter,
        PdfFormatOption,
        PowerpointFormatOption,
        WordFormatOption,
    )

    from .office import Powerpoint, Word

    settings = config["services"]["letfs_ingest"]["cpu"]
    options = PdfPipelineOptions(
        artifacts_path=settings["docling_models_path"],
        accelerator_options=AcceleratorOptions(device="cpu", num_threads=settings["threads"]),
        do_ocr=True, ocr_options=RapidOcrOptions(backend="onnxruntime", lang=["iso:en"]),
        generate_picture_images=True, ocr_batch_size=1, layout_batch_size=1,
        table_batch_size=1, queue_max_size=2,
        document_timeout=config["services"]["letfs"]["processing"]["parse_timeout_seconds"],
    )
    return DocumentConverter(
        allowed_formats=[InputFormat.PDF, InputFormat.DOCX, InputFormat.PPTX, InputFormat.XLSX],
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=options),
            InputFormat.DOCX: WordFormatOption(backend=Word),
            InputFormat.PPTX: PowerpointFormatOption(backend=Powerpoint),
        },
    )


def convert(source: Path, output: Path, media: str, config: Config) -> None:
    from docling.datamodel.base_models import ConversionStatus
    from PIL import Image

    from .export import document, spreadsheets

    settings = config["services"]["letfs_ingest"]["cpu"]
    limits = settings["limits"]
    preflight(source, media, config)
    Image.MAX_IMAGE_PIXELS = limits["max_page_pixels"]
    warnings.simplefilter("error", Image.DecompressionBombWarning)
    result = converter(config).convert(
        source, raises_on_error=False, max_num_pages=limits["max_pages"],
        max_file_size=config["services"]["letfs"]["max_blob_bytes"],
    )
    if result.status != ConversionStatus.SUCCESS:
        raise InvalidDocument("document conversion incomplete")
    if media.endswith("spreadsheetml.sheet"):
        spreadsheets(result.document, source, output)
    else:
        document(result.document, output, settings["min_section_tokens"], settings["split_tokens"], presentation=media.endswith("presentationml.presentation"))
    entries = list(output.rglob("*"))
    if len(entries) > config["services"]["letfs"]["processing"]["max_artifacts"] or sum(
        path.stat().st_size for path in entries if path.is_file()
    ) > limits["max_output_bytes"]:
        raise InvalidDocument("parser output exceeds budget")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("media_type")
    args = parser.parse_args()
    os.environ["HF_HUB_OFFLINE"] = "1"
    logging.basicConfig(level=logging.ERROR)
    try:
        convert(args.source, args.output, args.media_type, load())
    except InvalidDocument as error:
        print(str(error), file=sys.stderr)
        sys.exit(os.EX_DATAERR)
