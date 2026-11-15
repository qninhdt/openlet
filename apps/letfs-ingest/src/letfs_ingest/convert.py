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


def converter(config: Config) -> DocumentConverter:
    from docling.datamodel.accelerator_options import AcceleratorOptions
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import (
        ConvertPipelineOptions,
        HeadingHierarchyOptions,
        PdfPipelineOptions,
        TesseractCliOcrOptions,
    )
    from docling.document_converter import (
        DocumentConverter,
        ExcelFormatOption,
        PdfFormatOption,
        PowerpointFormatOption,
        WordFormatOption,
    )

    from .ocr import PdfPipeline
    from .office import Powerpoint, Word

    settings = config["services"]["letfs_ingest"]["cpu"]
    os.environ["OMP_THREAD_LIMIT"] = str(settings["threads"])
    options = PdfPipelineOptions(
        artifacts_path=settings["docling_models_path"],
        accelerator_options=AcceleratorOptions(
            device="cpu", num_threads=settings["threads"]
        ),
        do_ocr=True,
        ocr_options=TesseractCliOcrOptions(
            lang=["eng", "vie"], replace_broken_text_layer=True
        ),
        heading_hierarchy_options=HeadingHierarchyOptions(enabled=True),
        generate_page_images=True,
        generate_picture_images=True,
        do_picture_classification=True,
        ocr_batch_size=1,
        layout_batch_size=1,
        table_batch_size=1,
        queue_max_size=2,
        document_timeout=config["services"]["letfs"]["processing"][
            "parse_timeout_seconds"
        ],
    )
    office_options = ConvertPipelineOptions(
        artifacts_path=options.artifacts_path,
        accelerator_options=options.accelerator_options,
        do_picture_classification=True,
    )
    return DocumentConverter(
        allowed_formats=[
            InputFormat.PDF,
            InputFormat.DOCX,
            InputFormat.PPTX,
            InputFormat.XLSX,
        ],
        format_options={
            InputFormat.PDF: PdfFormatOption(
                pipeline_cls=PdfPipeline, pipeline_options=options
            ),
            InputFormat.DOCX: WordFormatOption(
                backend=Word, pipeline_options=office_options
            ),
            InputFormat.PPTX: PowerpointFormatOption(
                backend=Powerpoint, pipeline_options=office_options
            ),
            InputFormat.XLSX: ExcelFormatOption(pipeline_options=office_options),
        },
    )


def convert(
    source: Path,
    output: Path,
    media: str,
    config: Config,
    *,
    source_name: str | None = None,
) -> None:
    from docling.datamodel.base_models import ConversionStatus
    from PIL import Image

    from .export import document, spreadsheets

    settings = config["services"]["letfs_ingest"]["cpu"]
    limits = settings["limits"]
    preflight(source, media, config)
    Image.MAX_IMAGE_PIXELS = limits["max_page_pixels"]
    warnings.simplefilter("error", Image.DecompressionBombWarning)
    result = converter(config).convert(
        source,
        raises_on_error=False,
        max_num_pages=limits["max_pages"],
        max_file_size=config["services"]["letfs"]["max_blob_bytes"],
    )
    if result.status != ConversionStatus.SUCCESS:
        raise InvalidDocument("document conversion incomplete")
    if source_name:
        result.document.name = Path(source_name).stem
    try:
        if media.endswith("spreadsheetml.sheet"):
            spreadsheets(
                result.document,
                source,
                output,
                config["services"]["letfs"]["max_text_bytes"],
                split_tokens=settings["split_tokens"],
            )
        else:
            document(
                result.document,
                output,
                settings["split_tokens"],
                max_text_bytes=config["services"]["letfs"]["max_text_bytes"],
                presentation=media.endswith("presentationml.presentation"),
            )
    except ValueError as error:
        raise InvalidDocument(str(error)) from error
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
    os.environ["HF_HUB_OFFLINE"] = "1"
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
