import base64
import io

import pytest
from letfs_ingest.providers import Metadata, SemanticType, evidence, vision
from letfs_ingest.readme import own_body, render
from openlet_sdk.config import Config
from PIL import Image
from pydantic import ValidationError


def test_evidence_covers_middle_and_end_within_budget() -> None:
    text = "first topic " * 500 + "middle subject " * 1000 + "final topic " * 500
    sampled = evidence(text, "text/markdown", 800)
    assert len(sampled) <= 800
    assert all(
        topic in sampled for topic in ("first topic", "middle subject", "final topic")
    )
    csv = evidence("name,value\n" + "record,12\n" * 10000, "text/csv", 800)
    assert "name, value" in csv and csv.count("record, 12") == 8


def test_metadata_taxonomy_readme_body_and_image_size(config: Config) -> None:
    metadata = Metadata(
        title="  Report  ",
        description="Annual results",
        semantic_type=SemanticType.DOCUMENT_REPORT,
        context="Sales trends",
    )
    assert metadata.title == "Report"
    with pytest.raises(ValidationError):
        Metadata.model_validate(
            {**metadata.model_dump(), "semantic_type": "made-up:type"}
        )
    body = "# Original content\n\nKeep this evidence."
    rendered = render(metadata, body, {"table-1.csv": {"title": "Revenue"}})
    assert own_body(rendered) == body
    assert render(metadata, rendered, {}) == render(metadata, body, {})
    data = io.BytesIO()
    Image.new("RGBA", (2400, 1200), "red").save(data, "PNG")
    settings = config["models"]["enrichment"]
    settings.update(
        max_image_pixels=3000000, image_max_side=1600, image_jpeg_quality=85
    )
    encoded = vision(data.getvalue(), settings)
    with Image.open(io.BytesIO(base64.b64decode(encoded.split(",", 1)[1]))) as image:
        assert image.size == (1600, 800)
        assert image.mode == "RGB"
    with pytest.raises(ValueError, match="pixel limit"):
        vision(data.getvalue(), {**settings, "max_image_pixels": 10})
