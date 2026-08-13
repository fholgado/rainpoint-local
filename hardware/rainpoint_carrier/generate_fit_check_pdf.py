#!/usr/bin/env python3
"""Generate a dimensionally stable, printable carrier fit-check sheet."""

from __future__ import annotations

import argparse
from pathlib import Path

from reportlab.lib.colors import Color, HexColor, black, white
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas


BOARD_WIDTH_MM = 68.0
BOARD_HEIGHT_MM = 66.0
ESP_WIDTH_MM = 29.0
ESP_HEIGHT_MM = 51.74
ESP_ROW_SPACING_MM = 25.40
ESP_LEFT_ROW_X_MM = 9.68
ESP_RIGHT_ROW_X_MM = ESP_LEFT_ROW_X_MM + ESP_ROW_SPACING_MM
HEADER_PITCH_MM = 2.54
ESP_HEADER_PINS = 15


def _circle(canvas: Canvas, x_mm: float, y_mm: float, radius_mm: float) -> None:
    canvas.circle(x_mm * mm, y_mm * mm, radius_mm * mm, stroke=1, fill=0)


def _draw_carrier(canvas: Canvas, origin_x_mm: float, origin_y_mm: float) -> None:
    """Draw the Rev A placement using millimetre-native coordinates."""
    canvas.saveState()
    canvas.translate(origin_x_mm * mm, origin_y_mm * mm)

    canvas.setStrokeColor(black)
    canvas.setLineWidth(0.25 * mm)
    canvas.roundRect(
        0,
        0,
        BOARD_WIDTH_MM * mm,
        BOARD_HEIGHT_MM * mm,
        0.8 * mm,
        stroke=1,
        fill=0,
    )

    # Four 3.2 mm non-plated mounting holes.
    for x_mm, y_mm in ((3.5, 3.5), (64.5, 3.5), (3.5, 62.5), (64.5, 62.5)):
        _circle(canvas, x_mm, y_mm, 1.6)

    # ESP32 body and Wi-Fi antenna keepout. USB-C is at the bottom.
    canvas.setFillColor(HexColor("#dbeafe"))
    canvas.rect(8 * mm, 7 * mm, ESP_WIDTH_MM * mm, ESP_HEIGHT_MM * mm, fill=1)
    canvas.setFillColor(Color(1, 0.88, 0.88, alpha=0.72))
    canvas.setDash(1 * mm, 0.7 * mm)
    canvas.setStrokeColor(HexColor("#b91c1c"))
    canvas.rect(7 * mm, 47.5 * mm, 31 * mm, 18 * mm, fill=1)
    canvas.setDash()

    # Two 1x15 socket rows, anchored at the USB end. Coordinates match
    # LAYOUT.md and the physically verified 30-pin development board.
    canvas.setStrokeColor(HexColor("#6b4f00"))
    for index in range(ESP_HEADER_PINS):
        y_mm = 10.01 + index * HEADER_PITCH_MM
        _circle(canvas, ESP_LEFT_ROW_X_MM, y_mm, 0.95)
        _circle(canvas, ESP_RIGHT_ROW_X_MM, y_mm, 0.95)

    # CC1101 body and its 2x4 socket.
    canvas.setFillColor(HexColor("#dcfce7"))
    canvas.setStrokeColor(HexColor("#166534"))
    canvas.rect(39 * mm, 25.5 * mm, 28 * mm, 15 * mm, fill=1)
    canvas.setStrokeColor(HexColor("#6b4f00"))
    for row in range(4):
        y_mm = 29.19 + row * HEADER_PITCH_MM
        _circle(canvas, 41.0, y_mm, 1.05)
        _circle(canvas, 43.54, y_mm, 1.05)

    canvas.setFillColor(black)
    canvas.setFont("Helvetica-Bold", 7)
    canvas.drawString(11 * mm, 32 * mm, "ELEGOO EL-SM-012")
    canvas.setFont("Helvetica", 6.5)
    canvas.drawString(17 * mm, 8.2 * mm, "USB-C")
    canvas.setFillColor(HexColor("#b91c1c"))
    canvas.setFont("Helvetica-Bold", 6)
    canvas.drawString(10.5 * mm, 61.5 * mm, "NO COPPER - WI-FI ANTENNA")
    canvas.setFillColor(black)
    canvas.setFont("Helvetica-Bold", 7)
    canvas.drawCentredString(53 * mm, 32.5 * mm, "CC1101")
    canvas.setFont("Helvetica", 6)
    canvas.drawString(56 * mm, 23.5 * mm, "433 MHz antenna ->")

    # Explicit row-spacing dimension.
    dim_y = 4.3
    canvas.setStrokeColor(HexColor("#2563eb"))
    canvas.line(ESP_LEFT_ROW_X_MM * mm, dim_y * mm, ESP_RIGHT_ROW_X_MM * mm, dim_y * mm)
    for x_mm in (ESP_LEFT_ROW_X_MM, ESP_RIGHT_ROW_X_MM):
        canvas.line(x_mm * mm, 3.3 * mm, x_mm * mm, 5.3 * mm)
    canvas.setFillColor(HexColor("#1d4ed8"))
    canvas.setFont("Helvetica-Bold", 6.5)
    canvas.drawCentredString(
        (ESP_LEFT_ROW_X_MM + ESP_ROW_SPACING_MM / 2) * mm,
        1.6 * mm,
        "25.40 mm header-row centers",
    )
    canvas.restoreState()


def _draw_calibration(canvas: Canvas, x_mm: float, y_mm: float) -> None:
    """Draw independent metric and imperial scale checks."""
    canvas.saveState()
    canvas.translate(x_mm * mm, y_mm * mm)
    canvas.setStrokeColor(black)
    canvas.setFillColor(black)
    canvas.setLineWidth(0.25 * mm)

    # 100 mm ruler with 1 mm ticks and labelled 10 mm intervals.
    canvas.line(0, 0, 100 * mm, 0)
    for value in range(101):
        height = 4 if value % 10 == 0 else 2 if value % 5 == 0 else 1
        canvas.line(value * mm, 0, value * mm, height * mm)
        if value % 10 == 0:
            canvas.setFont("Helvetica", 6)
            canvas.drawCentredString(value * mm, 5 * mm, str(value))
    canvas.setFont("Helvetica-Bold", 7)
    canvas.drawString(0, 8 * mm, "100 mm calibration ruler")

    # Exact one-inch square catches unit conversion and nonuniform scaling.
    square_x = 112 * mm
    canvas.rect(square_x, 0, 25.4 * mm, 25.4 * mm, stroke=1, fill=0)
    canvas.setFont("Helvetica-Bold", 7)
    canvas.drawCentredString(square_x + 12.7 * mm, 27.5 * mm, "1 inch")
    canvas.setFont("Helvetica", 6)
    canvas.drawCentredString(square_x + 12.7 * mm, 12 * mm, "25.4 mm")
    canvas.restoreState()


def generate(output: Path) -> None:
    """Create a US Letter PDF that printers can reproduce at exact scale."""
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas = Canvas(str(output), pagesize=letter, pageCompression=1)
    width, height = letter
    canvas.setTitle("RainPoint radio-node carrier Rev A - 1:1 fit check")
    canvas.setAuthor("RainPoint Local project")

    canvas.setFillColor(black)
    canvas.setFont("Helvetica-Bold", 15)
    canvas.drawString(16 * mm, height - 17 * mm, "RainPoint carrier Rev A - 1:1 fit check")
    canvas.setFont("Helvetica-Bold", 9)
    canvas.setFillColor(HexColor("#b91c1c"))
    canvas.drawString(16 * mm, height - 25 * mm, "PRINT AT ACTUAL SIZE / 100%")
    canvas.setFillColor(black)
    canvas.setFont("Helvetica", 8)
    canvas.drawString(
        16 * mm,
        height - 31 * mm,
        "Disable Fit, Shrink oversized pages, and Scale to printable area.",
    )
    canvas.drawString(
        16 * mm,
        height - 36 * mm,
        "First measure the 100 mm ruler and 1 inch square. If either is off, do not assess the footprint.",
    )

    _draw_carrier(canvas, 16, 102)
    _draw_calibration(canvas, 16, 55)

    canvas.setFont("Helvetica", 7.5)
    canvas.drawString(16 * mm, 44 * mm, "Nominal carrier outline: 68 x 66 mm")
    canvas.drawString(16 * mm, 39 * mm, "ESP32 outline: 29 x 51.74 mm; 2 x 15 pins at 2.54 mm pitch")
    canvas.drawString(16 * mm, 34 * mm, "ESP32 header-row center spacing: 25.40 mm (verify against the physical board)")
    canvas.drawString(16 * mm, 29 * mm, "CC1101 connector: 2 x 4 pins at 2.54 mm pitch")
    canvas.setFont("Helvetica-Bold", 7.5)
    canvas.drawString(16 * mm, 20 * mm, "Do not fabricate from this fit sheet until both modules physically align.")
    canvas.setFont("Helvetica", 6.5)
    canvas.setFillColor(HexColor("#4b5563"))
    canvas.drawRightString(width - 16 * mm, 12 * mm, "Generated from millimetre-native vector geometry")

    canvas.showPage()
    canvas.save()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    generate(args.output)


if __name__ == "__main__":
    main()
