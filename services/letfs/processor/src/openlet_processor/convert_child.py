import errno
import os
import resource
import sys
import warnings
from pathlib import Path, PurePosixPath
from zipfile import BadZipFile, ZipFile

from PIL import Image

from openlet_processor.models import LAYOUT_REPO, LAYOUT_REVISION

MAX_INPUT_BYTES = 104857600
MAX_PAGES = 200
MAX_PAGE_PIXELS = 25000000
MAX_CELLS = 1000000
MAX_SCRATCH_BYTES = 1073741824


class ResourceLimit(Exception):
    pass


def preflight(source: Path, kind: str) -> None:
    if source.stat().st_size > MAX_INPUT_BYTES:
        raise ResourceLimit("input bytes")
    if kind == "pdf":
        import pypdfium2

        document = pypdfium2.PdfDocument(source)
        try:
            if len(document) > MAX_PAGES:
                raise ResourceLimit("pages")
            for page in document:
                try:
                    width, height = page.get_size()
                    if width * height * 9 > MAX_PAGE_PIXELS:
                        raise ResourceLimit("page pixels")
                finally:
                    page.close()
        finally:
            document.close()
    else:
        with ZipFile(source) as archive:
            entries = archive.infolist()
            if len(entries) > 10000 or sum(e.file_size for e in entries) > 536870912:
                raise ResourceLimit("expanded document bytes")
            if any(
                PurePosixPath(e.filename).is_absolute()
                or ".." in PurePosixPath(e.filename).parts
                or "\\" in e.filename
                for e in entries
            ):
                raise ValueError("invalid document member path")
        if kind == "xlsx":
            from openpyxl import load_workbook

            workbook = load_workbook(source, read_only=True)
            try:
                cells = sum(s.max_row * s.max_column for s in workbook.worksheets)
                if len(workbook.worksheets) > 100 or cells > MAX_CELLS:
                    raise ResourceLimit("spreadsheet cells")
            finally:
                workbook.close()


def check_outputs(output: Path, max_outputs: int, max_bytes: int) -> None:
    entries = list(output.rglob("*"))
    if len(entries) > max_outputs:
        raise ResourceLimit("output entries")
    if any(e.is_symlink() for e in entries):
        raise ValueError("output symlink")
    if sum(e.stat().st_size for e in entries if e.is_file()) > max_bytes:
        raise ResourceLimit("output bytes")


def convert(
    source: Path,
    output: Path,
    kind: str,
    models: Path,
    max_outputs: int = 512,
    max_bytes: int = 268435456,
) -> None:
    from docling.datamodel.accelerator_options import AcceleratorOptions
    from docling.datamodel.base_models import ConversionStatus, InputFormat
    from docling.datamodel.pipeline_options import (
        LayoutObjectDetectionOptions,
        PdfPipelineOptions,
        RapidOcrOptions,
    )
    from docling.datamodel.stage_model_specs import ObjectDetectionModelSpec
    from docling.document_converter import (
        DocumentConverter,
        PdfFormatOption,
        PowerpointFormatOption,
        WordFormatOption,
    )
    from docling_core.utils.settings import settings

    from openlet_processor.exporters import markdown, spreadsheets
    from openlet_processor.powerpoint import PowerpointBackend
    from openlet_processor.word import WordBackend

    formats = {
        "pdf": InputFormat.PDF,
        "docx": InputFormat.DOCX,
        "pptx": InputFormat.PPTX,
        "xlsx": InputFormat.XLSX,
    }
    if kind not in formats:
        raise ValueError("unsupported input format")
    preflight(source, kind)
    settings.max_image_decoded_size = min(MAX_PAGE_PIXELS * 4, max_bytes)
    Image.MAX_IMAGE_PIXELS = MAX_PAGE_PIXELS
    warnings.simplefilter("error", Image.DecompressionBombWarning)
    options = PdfPipelineOptions(
        artifacts_path=models,
        accelerator_options=AcceleratorOptions(device="cpu", num_threads=2),
        enable_remote_services=False,
        allow_external_plugins=False,
        document_timeout=600,
        queue_max_size=2,
        ocr_batch_size=1,
        layout_batch_size=1,
        table_batch_size=1,
        generate_picture_images=True,
        do_picture_classification=False,
        do_picture_description=False,
        do_code_enrichment=False,
        do_formula_enrichment=False,
        layout_options=LayoutObjectDetectionOptions(
            model_spec=ObjectDetectionModelSpec(
                name="docling_layout_heron",
                repo_id=LAYOUT_REPO,
                revision=LAYOUT_REVISION,
            ),
        ),
        ocr_options=RapidOcrOptions(lang=["iso:en"]),
    )
    converter = DocumentConverter(
        allowed_formats=[formats[kind]],
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=options),
            InputFormat.PPTX: PowerpointFormatOption(backend=PowerpointBackend),
            InputFormat.DOCX: WordFormatOption(backend=WordBackend),
        },
    )
    result = converter.convert(
        source,
        max_num_pages=MAX_PAGES,
        max_file_size=MAX_INPUT_BYTES,
    )
    if result.status != ConversionStatus.SUCCESS:
        raise ValueError("document conversion incomplete")
    document = result.document
    if len(document.tables) > 2000 or len(document.pictures) > max_outputs:
        raise ResourceLimit("document elements")
    if len(document.pages) > MAX_PAGES:
        raise ResourceLimit("document pages")
    for picture in document.pictures:
        if picture.image and (
            picture.image.size.width * picture.image.size.height > MAX_PAGE_PIXELS
        ):
            raise ResourceLimit("image pixels")
    if kind == "xlsx":
        spreadsheets(document, source, output)
    else:
        markdown(document, output, kind)
    check_outputs(output, max_outputs, max_bytes)


def main() -> int:
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_CPU, (1200, 1210))
    resource.setrlimit(resource.RLIMIT_AS, (6442450944, 6442450944))
    resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_SCRATCH_BYTES, MAX_SCRATCH_BYTES))
    resource.setrlimit(resource.RLIMIT_NOFILE, (256, 256))
    os.umask(0o077)
    try:
        convert(
            Path(sys.argv[1]),
            Path(sys.argv[2]),
            sys.argv[3],
            Path(sys.argv[4]),
            int(sys.argv[5]),
            int(sys.argv[6]),
        )
        return 0
    except Exception as error:
        code = failure_exit_code(error)
        cause = error.__cause__ or error.__context__
        print(
            f"OPENLET_CONVERSION_ERROR exit={code} exception={type(error).__name__} "
            f"cause={type(cause).__name__} "
            f"peak_rss_kib={resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}",
            file=sys.stderr,
        )
        return code


def failure_exit_code(error: Exception) -> int:
    from docling.exceptions import ConversionError, DocumentLoadError

    current = error
    while current is not None:
        if isinstance(current, (ResourceLimit, MemoryError)) or (
            isinstance(current, OSError)
            and current.errno in {errno.ENOMEM, errno.ENOSPC, errno.EMFILE, errno.EFBIG}
        ):
            return 3
        # Docling wraps native allocator failures and image limits as conversion errors.
        if any(
            marker in str(current)
            for marker in (
                "std::bad_alloc",
                "DefaultCPUAllocator: can't allocate memory",
                "Unable to allocate",
                "Decoded image exceeds size limit",
            )
        ):
            return 3
        current = current.__cause__ or current.__context__
    if isinstance(error, (ValueError, BadZipFile, ConversionError, DocumentLoadError)):
        return 2
    return 4


if __name__ == "__main__":
    sys.exit(main())
