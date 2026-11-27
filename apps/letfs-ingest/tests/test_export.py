import csv
import zipfile
from copy import deepcopy
from io import BytesIO, StringIO
from pathlib import Path

import openpyxl
import pytest
from letfs_ingest.convert import (
    PDF_MEDIA,
    PPTX_MEDIA,
    XLSX_MEDIA,
    InvalidDocument,
    convert,
    preflight,
    validate_output,
)
from lxml import etree
from openlet_sdk.config import Config
from PIL import Image, ImageDraw
from pptx import Presentation
from pptx.chart.data import ChartData
from pptx.enum.chart import XL_CHART_TYPE
from pptx.util import Inches
from pypdf import PdfWriter


def _textured_png(size: tuple[int, int] = (120, 80), accent: str = "navy") -> bytes:
    img = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(img)
    w, h = size
    draw.rectangle([2, 2, max(3, w // 3), max(3, h - 2)], fill=accent)
    draw.rectangle([max(4, w // 2), 2, max(5, w - 2), max(3, h - 2)], fill="teal")
    draw.line([(0, 0), size], fill="black", width=2)
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _solid_png(size: tuple[int, int] = (60, 60)) -> bytes:
    img = Image.new("RGB", size, "white")
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_powerpoint_extracts_charts_notes_groups_and_drops_noise_images(
    tmp_path: Path, config: Config
) -> None:
    prs = Presentation()
    blank = prs.slide_layouts[6]

    chart_img = tmp_path / "chart.png"
    chart_img.write_bytes(_textured_png((120, 80)))
    tiny_icon = tmp_path / "tiny.png"
    tiny_icon.write_bytes(_textured_png((16, 16)))
    solid_box = tmp_path / "solid.png"
    solid_box.write_bytes(_solid_png((64, 64)))
    logo = tmp_path / "logo.png"
    logo.write_bytes(_textured_png((80, 50), accent="crimson"))

    for i in range(4):
        slide = prs.slides.add_slide(blank)
        slide.shapes.add_picture(str(logo), Inches(8), Inches(0.2), width=Inches(1))
        if i == 0:
            box = slide.shapes.add_textbox(
                Inches(0.5), Inches(0.5), Inches(5), Inches(1)
            )
            box.text_frame.text = "Sales Review"
            slide.shapes.add_picture(str(chart_img), Inches(1), Inches(2))
            slide.shapes.add_picture(str(tiny_icon), Inches(0.1), Inches(0.1))
            slide.shapes.add_picture(str(solid_box), Inches(0.2), Inches(0.2))
            data = ChartData()
            data.categories = ["Q1", "Q2"]
            data.add_series("Revenue", (100, 140))  # pyright: ignore[reportUnknownMemberType]
            slide.shapes.add_chart(
                XL_CHART_TYPE.COLUMN_CLUSTERED,
                Inches(3),
                Inches(2),
                Inches(4),
                Inches(3),
                data,
            )
            notes_tf = slide.notes_slide.notes_text_frame
            assert notes_tf is not None
            notes_tf.text = "Focus on Q2 surge"
        else:
            box = slide.shapes.add_textbox(
                Inches(0.5), Inches(0.5), Inches(5), Inches(1)
            )
            box.text_frame.text = f"Slide body {i}"

    src = tmp_path / "deck.pptx"
    prs.save(str(src))
    out = tmp_path / "out"
    convert(src, PPTX_MEDIA, out, config)

    combined = "\n".join(p.read_text() for p in out.glob("*.md"))
    assert "Sales Review" in combined
    assert "### Chart" in combined and "| Q1 | 100.0 |" in combined
    assert "> Speaker Notes: Focus on Q2 surge" in combined

    saved_images = list((out / "images").glob("*"))
    # Only the genuine textured chart image survives (logo on 4/4 slides, tiny 16x16, and solid blank are dropped).
    assert len(saved_images) == 1
    assert saved_images[0].read_bytes() == chart_img.read_bytes()


def test_xlsx_xy_cut_segments_separate_tables_and_renders_clean_csv(
    tmp_path: Path, config: Config
) -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = "Financials"
    # Table 1 with 1-row banner title above
    ws["A1"] = "Revenue Summary"
    ws["A3"] = "Region"
    ws["B3"] = "Revenue"
    ws["A4"] = "APAC"
    ws["B4"] = 250
    ws["A5"] = "EMEA"
    ws["B5"] = 180
    # Separated horizontally by blank col C + blank row 6
    ws["D7"] = "Product"
    ws["E7"] = "Units"
    ws["D8"] = "Widget"
    ws["E8"] = 42

    src = tmp_path / "model.xlsx"
    wb.save(src)
    wb.close()

    out = tmp_path / "xlsx_out"
    convert(src, XLSX_MEDIA, out, config)

    csv_files = sorted((out / "tables").glob("*.csv"))
    assert len(csv_files) == 2
    t1 = list(csv.reader(StringIO(csv_files[0].read_text())))
    t2 = list(csv.reader(StringIO(csv_files[1].read_text())))
    assert t1 == [["Region", "Revenue"], ["APAC", "250"], ["EMEA", "180"]]
    assert t2 == [["Product", "Units"], ["Widget", "42"]]

    readme = (out / "README.md").read_text()
    assert "Revenue Summary" in readme
    assert "tables/01-financials.csv" in readme
    assert "tables/02-financials.csv" in readme


def test_xlsx_xy_cut_keeps_left_label_column_across_single_blank_spacer(
    tmp_path: Path, config: Config
) -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = "Operating"
    # Left row labels in col B, blank spacer col C, numbers in col D..F
    ws["B2"] = "Revenue"
    ws["B3"] = "OpEx"
    ws["D2"] = 100.5
    ws["E2"] = 112.0
    ws["F2"] = 125.0
    ws["D3"] = 60.0
    ws["E3"] = 65.0
    ws["F3"] = 70.0

    src = tmp_path / "lbo.xlsx"
    wb.save(src)
    wb.close()

    out = tmp_path / "lbo_out"
    convert(src, XLSX_MEDIA, out, config)
    csv_files = sorted((out / "tables").glob("*.csv"))
    assert len(csv_files) == 1
    rows = list(csv.reader(StringIO(csv_files[0].read_text())))
    assert rows == [
        ["Revenue", "100.5", "112", "125"],
        ["OpEx", "60", "65", "70"],
    ]


def test_xlsx_sparse_bfs_merges_headers_indents_and_inlines_prose_notes(
    tmp_path: Path, config: Config
) -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = "P&L"
    # Merged banner across cols A..E -> peeled cleanly, NOT repeated 5x in CSV
    ws.merge_cells("A1:E1")
    ws["A1"] = "Annual P&L Summary"
    # Multi-tier header (2024 over Q1/Q2) + 1 blank row before numeric rows
    ws.merge_cells("B2:C2")
    ws.merge_cells("D2:E2")
    ws["B2"] = 2024
    ws["D2"] = 2025
    ws["B3"], ws["C3"], ws["D3"], ws["E3"] = "Q1", "Q2", "Q1", "Q2"
    # Row labels in col A with empty cols B..C (gap=2) for 2024, values start in col D..E
    ws["A5"], ws["D5"], ws["E5"] = "Revenue", 100, 120
    # 1 blank row separating second P&L section on same columns
    ws["A7"], ws["D7"], ws["E7"] = "EBITDA", 30, 40
    # Narrative callout note separated below -> inlined into README.md, not CSV
    ws["A10"] = "Note: Margins reflect international launch costs across Europe."

    # Separate second block on row 12 with new all-text header -> must remain separate CSV
    ws["A12"], ws["B12"] = "Cost Driver", "Owner"
    ws["A13"], ws["B13"] = "Freight", "Ops"

    src = tmp_path / "financials.xlsx"
    wb.save(src)
    wb.close()

    out = tmp_path / "fin_out"
    convert(src, XLSX_MEDIA, out, config)

    csv_files = sorted((out / "tables").glob("*.csv"))
    assert len(csv_files) == 2
    t1 = list(csv.reader(StringIO(csv_files[0].read_text())))
    assert t1 == [
        ["", "2024", "2024", "2025", "2025"],
        ["", "Q1", "Q2", "Q1", "Q2"],
        ["Revenue", "", "", "100", "120"],
        ["EBITDA", "", "", "30", "40"],
    ]
    t2 = list(csv.reader(StringIO(csv_files[1].read_text())))
    assert t2 == [["Cost Driver", "Owner"], ["Freight", "Ops"]]

    readme = (out / "README.md").read_text()
    assert "Annual P&L Summary" in readme
    assert "Note: Margins reflect international launch costs" in readme


def test_input_limits_reject_expanded_office_and_oversized_spreadsheet(
    tmp_path: Path, config: Config
) -> None:
    cfg = deepcopy(config)
    cfg["services"]["letfs_ingest"]["cpu"]["limits"]["max_office_expanded_bytes"] = 64
    small_zip = tmp_path / "large.pptx"
    with zipfile.ZipFile(small_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("ppt/slides/slide1.xml", etree.tostring(etree.Element("sld")) * 20)
    with pytest.raises(InvalidDocument, match="expanded size"):
        preflight(small_zip, PPTX_MEDIA, cfg)

    cfg = deepcopy(config)
    cfg["services"]["letfs_ingest"]["cpu"]["limits"]["max_spreadsheet_cells"] = 4
    wb = openpyxl.Workbook()
    ws = wb.active
    assert ws is not None
    for r in range(1, 5):
        for c in range(1, 3):
            ws.cell(r, c, "x")
    xlsx_path = tmp_path / "cells.xlsx"
    wb.save(xlsx_path)
    wb.close()
    with pytest.raises(InvalidDocument, match="cell count"):
        preflight(xlsx_path, XLSX_MEDIA, cfg)


def test_conversion_rejects_text_limit_before_publish(
    tmp_path: Path, config: Config
) -> None:
    cfg = deepcopy(config)
    cfg["services"]["letfs"]["processing"]["max_manifest_text_bytes"] = 10
    (tmp_path / "README.md").write_text("more than ten bytes")
    with pytest.raises(InvalidDocument, match="max_manifest_text_bytes"):
        validate_output(tmp_path, cfg)


def test_pdf_preflight_validates_pages_pixels_and_corrupt_files(
    tmp_path: Path, config: Config
) -> None:
    ok_pdf = tmp_path / "ok.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=300)
    writer.add_blank_page(width=200, height=300)
    with ok_pdf.open("wb") as fh:
        writer.write(fh)

    cfg = deepcopy(config)
    cfg["services"]["letfs_ingest"]["cpu"]["limits"]["max_pages"] = 2
    cfg["services"]["letfs_ingest"]["cpu"]["limits"]["max_page_pixels"] = 70_000
    preflight(ok_pdf, PDF_MEDIA, cfg)

    cfg["services"]["letfs_ingest"]["cpu"]["limits"]["max_pages"] = 1
    with pytest.raises(InvalidDocument, match="exceeding limit 1"):
        preflight(ok_pdf, PDF_MEDIA, cfg)

    cfg["services"]["letfs_ingest"]["cpu"]["limits"]["max_pages"] = 2
    cfg["services"]["letfs_ingest"]["cpu"]["limits"]["max_page_pixels"] = 50_000
    with pytest.raises(InvalidDocument, match="pixel limit"):
        preflight(ok_pdf, PDF_MEDIA, cfg)

    bad_pdf = tmp_path / "bad.pdf"
    bad_pdf.write_bytes(b"not a pdf")
    with pytest.raises(InvalidDocument, match="invalid PDF"):
        preflight(bad_pdf, PDF_MEDIA, cfg)


def test_xlsx_bridges_header_unit_note_and_horizontal_year_gaps(
    tmp_path: Path, config: Config
) -> None:
    wb = openpyxl.Workbook()
    # Sheet 1: SATS-style header band separated from data by 1-cell unit note in col A
    ws1 = wb.active
    assert ws1 is not None
    ws1.title = "Quarterly"
    ws1.merge_cells("B2:C2")
    ws1.merge_cells("D2:E2")
    ws1["B2"], ws1["D2"] = 2024, 2025
    ws1["B3"], ws1["C3"], ws1["D3"], ws1["E3"] = "Q1", "Q2", "Q1", "Q2"
    ws1["A4"] = "Amounts in NOK million"
    ws1["A6"], ws1["B6"], ws1["C6"], ws1["D6"], ws1["E6"] = (
        "Revenue",
        100,
        120,
        130,
        140,
    )
    ws1["A7"], ws1["B7"], ws1["C7"], ws1["D7"], ws1["E7"] = "EBITDA", 30, 40, 42, 48

    # Sheet 2: Working-capital schedule with 1 blank FY column separating numeric year chunks
    ws2 = wb.create_sheet("WorkingCap")
    ws2["A1"] = "Receivables"
    ws2["A2"], ws2["B2"] = "Balance", 40.0
    ws2["A3"], ws2["B3"] = "% Sales", 0.04
    ws2["D2"], ws2["E2"] = 23.8, 41.3
    ws2["D3"], ws2["E3"] = 0.02, 0.03
    ws2["G2"], ws2["H2"] = 38.6, 72.8
    ws2["G3"], ws2["H3"] = 0.03, 0.05
    # Independent side-by-side table starting with a text column after 1 blank col must stay separate
    ws2["J2"], ws2["K2"] = "Owner", 10
    ws2["J3"], ws2["K3"] = "Ops", 20

    src = tmp_path / "merged_cases.xlsx"
    wb.save(src)
    wb.close()

    out = tmp_path / "out"
    convert(src, XLSX_MEDIA, out, config)

    csv_files = sorted((out / "tables").glob("*.csv"))
    assert len(csv_files) == 3

    sats_rows = list(csv.reader(StringIO(csv_files[0].read_text())))
    assert sats_rows[0] == ["", "2024", "2024", "2025", "2025"]
    assert sats_rows[1] == ["", "Q1", "Q2", "Q1", "Q2"]
    assert ["Revenue", "100", "120", "130", "140"] in sats_rows

    wc_rows = list(csv.reader(StringIO(csv_files[1].read_text())))
    assert wc_rows == [
        ["Balance", "40", "23.8", "41.3", "38.6", "72.8"],
        ["% Sales", "0.04", "0.02", "0.03", "0.03", "0.05"],
    ]
    assert list(csv.reader(StringIO(csv_files[2].read_text()))) == [
        ["Owner", "10"],
        ["Ops", "20"],
    ]
    readme = (out / "README.md").read_text()
    assert "Receivables" in readme
    assert "Amounts in NOK million" in "\n".join(",".join(r) for r in sats_rows)


def test_xlsx_multibyte_utf8_readme_stays_within_max_text_bytes(
    tmp_path: Path, config: Config
) -> None:
    wb = openpyxl.Workbook()
    for idx in range(4):
        ws = wb.active if idx == 0 else wb.create_sheet()
        assert ws is not None
        ws.title = f"Báo cáo Quý {idx + 1}"
        ws["A1"], ws["B1"] = "Mục", "Giá trị"
        ws["A2"], ws["B2"] = "Doanh thu", 100 + idx
    src = tmp_path / "utf8_index.xlsx"
    wb.save(src)
    wb.close()

    cfg = deepcopy(config)
    cfg["services"]["letfs"]["max_text_bytes"] = 90
    out = tmp_path / "out_utf8"
    convert(src, XLSX_MEDIA, out, cfg)
    readme_bytes = (out / "README.md").read_bytes()
    assert len(readme_bytes) <= 90
    assert readme_bytes.decode("utf-8").startswith("# Workbook Index")


def test_pptx_chart_header_escapes_pipe_characters(
    tmp_path: Path, config: Config
) -> None:
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[5])
    chart_data = ChartData()
    chart_data.categories = ["2024", "2025"]
    chart_data.add_series("Q1|Actual", (10.0, 20.0))  # pyright: ignore[reportUnknownMemberType]
    slide.shapes.add_chart(
        XL_CHART_TYPE.COLUMN_CLUSTERED,
        Inches(1),
        Inches(1),
        Inches(4),
        Inches(3),
        chart_data,
    )
    src = tmp_path / "chart_pipe.pptx"
    prs.save(str(src))

    out = tmp_path / "out_chart"
    convert(src, PPTX_MEDIA, out, config)
    readme = (out / "README.md").read_text()
    assert "| Category | Q1\\|Actual |" in readme
