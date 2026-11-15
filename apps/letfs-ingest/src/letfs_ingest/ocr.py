from pathlib import Path
from typing import cast

import pandas as pd  # pyright: ignore[reportMissingTypeStubs]  # Docling's OCR result type has no bundled stubs.
from docling.datamodel.pipeline_options import TesseractCliOcrOptions
from docling.models.stages.ocr.tesseract_ocr_cli_model import TesseractOcrCliModel
from docling.pipeline.standard_pdf_pipeline import StandardPdfPipeline


class Tesseract(TesseractOcrCliModel):
    def _perform_osd(self, ifilename: str) -> pd.DataFrame:
        result = super()._perform_osd(ifilename)
        confidence = float(
            result.loc[result["key"] == "Orientation confidence", "value"].iloc[0]  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]  # pandas indexing lacks stubs.
        )
        # Sparse crops can produce an upside-down guess with almost no confidence.
        if confidence < 15:
            result.loc[result["key"] == "Orientation in degrees", "value"] = "0"
        return result


class PdfPipeline(StandardPdfPipeline):
    # shortcut: uses Docling's internal OCR hook, recheck when upgrading Docling.
    def _make_ocr_model(self, art_path: Path | None) -> Tesseract:
        return Tesseract(
            enabled=self.pipeline_options.do_ocr,
            options=cast(TesseractCliOcrOptions, self.pipeline_options.ocr_options),
            artifacts_path=art_path,
            accelerator_options=self.pipeline_options.accelerator_options,
        )
