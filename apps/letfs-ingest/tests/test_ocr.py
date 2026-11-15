import pandas as pd  # pyright: ignore[reportMissingTypeStubs]  # Upstream has no bundled stubs.
import pytest
from docling.models.stages.ocr.tesseract_ocr_cli_model import TesseractOcrCliModel
from letfs_ingest.ocr import Tesseract


@pytest.mark.parametrize(
    "orientation,confidence,expected",
    [(180, 0.11, 0), (90, 14.9, 0), (180, 15, 180), (270, 20, 270), (0, 20, 0)],
)
def test_rotation_requires_confident_orientation(
    monkeypatch: pytest.MonkeyPatch,
    orientation: int,
    confidence: float,
    expected: int,
) -> None:
    result = pd.DataFrame(
        {
            "key": ["Orientation in degrees", "Orientation confidence", "Script"],
            "value": [str(orientation), str(confidence), "Latin"],
        }
    )

    def osd(self: TesseractOcrCliModel, filename: str) -> pd.DataFrame:
        return result

    monkeypatch.setattr(TesseractOcrCliModel, "_perform_osd", osd)
    model = object.__new__(Tesseract)
    actual = model._perform_osd("crop.png")  # pyright: ignore[reportPrivateUsage]  # Regression covers the overridden upstream hook.
    assert actual.iloc[0]["value"] == str(expected)
    assert actual.iloc[2]["value"] == "Latin"
