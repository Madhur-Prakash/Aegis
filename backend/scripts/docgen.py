"""Real document and image generation for the synthetic corpus.

The evidence bundles contain genuine PDFs with a real text layer and genuine
PNGs with real pixels, so the extraction path is actually exercised rather than
mocked.
"""

from __future__ import annotations

import datetime as dt
import io
import random
from dataclasses import dataclass
from typing import Any

from PIL import Image, ImageDraw, ImageFilter
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

# The approved fabric colour used across the demo and the corpus.
IVORY = (239, 231, 211)


@dataclass(slots=True)
class DocSpec:
    kind: str
    fields: dict[str, Any]
    line_items: list[dict[str, Any]]
    degrade: bool = False
    stated_total_override: float | None = None


def _line(c: canvas.Canvas, y: float, label: str, value: str, *, size: int = 10) -> float:
    c.setFont("Helvetica", size)
    c.drawString(22 * mm, y, f"{label}: {value}")
    return y - 6.2 * mm


def render_pdf(spec: DocSpec) -> bytes:
    """A one-page document whose ``label: value`` lines the analyser can read."""
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    title = {
        "INVOICE": "SUPPLIER INVOICE",
        "GRN": "GOODS RECEIPT NOTE",
        "DELIVERY_CHALLAN": "DELIVERY CHALLAN",
        "CONDITION_REPORT": "CONDITION REPORT",
        "SPEC_REFERENCE": "APPROVED SPECIFICATION",
    }.get(spec.kind, spec.kind)

    c.setFont("Helvetica-Bold", 15)
    c.drawString(22 * mm, height - 26 * mm, title)
    c.setLineWidth(0.6)
    c.line(22 * mm, height - 29 * mm, width - 22 * mm, height - 29 * mm)

    y = height - 40 * mm
    for label, value in spec.fields.items():
        if value is None:
            continue
        y = _line(c, y, label.replace("_", " ").title(), str(value))

    if spec.line_items:
        y -= 3 * mm
        c.setFont("Helvetica-Bold", 10)
        c.drawString(22 * mm, y, "Line items")
        y -= 6 * mm
        c.setFont("Courier", 9)
        for item in spec.line_items:
            row = (
                f"{str(item['description'])[:28].ljust(30)}"
                f"{item['quantity']:>10}  {item['uom']!s:<5} {item['amount']:>12}"
            )
            c.drawString(22 * mm, y, row)
            y -= 5 * mm
        total = spec.stated_total_override
        if total is None:
            total = sum(float(i["amount"]) for i in spec.line_items)
        y -= 2 * mm
        c.setFont("Helvetica-Bold", 10)
        c.drawString(22 * mm, y, f"Total: INR {total:.2f}")
        y -= 8 * mm

    c.setFont("Helvetica", 7.5)
    c.drawString(
        22 * mm,
        18 * mm,
        "Generated for the Aegis synthetic evaluation corpus. Not a real commercial document.",
    )
    c.showPage()
    c.save()
    data = buffer.getvalue()

    if spec.degrade:
        # A low-quality scan: the text layer is stripped, so the analyser
        # correctly reports that almost nothing is recoverable.
        return render_degraded_scan(spec)
    return data


def render_degraded_scan(spec: DocSpec) -> bytes:
    """A scan with no usable text layer: a rasterised, blurred, low-contrast page."""
    img = Image.new("RGB", (620, 880), (238, 236, 231))
    draw = ImageDraw.Draw(img)
    rng = random.Random(hash(str(spec.fields)) & 0xFFFF)
    for i in range(28):
        y = 90 + i * 26
        w = rng.randint(180, 460)
        grey = rng.randint(150, 195)
        draw.rectangle([60, y, 60 + w, y + 9], fill=(grey, grey, grey))
    img = img.filter(ImageFilter.GaussianBlur(radius=2.4))

    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    raster = io.BytesIO()
    img.save(raster, format="PNG")
    raster.seek(0)
    from reportlab.lib.utils import ImageReader

    c.drawImage(ImageReader(raster), 15 * mm, 15 * mm, width=180 * mm, height=250 * mm)
    c.showPage()
    c.save()
    return buffer.getvalue()


def render_photo(
    *,
    seed: int,
    colour: tuple[int, int, int] = IVORY,
    size: tuple[int, int] = (1280, 960),
    blur: float = 0.0,
    garments: int = 6,
) -> bytes:
    """A synthetic garment photograph.

    Deliberately shows a handful of items on a rail: enough to establish a colour
    family and that goods exist, and not enough to establish a batch count.  That
    limitation is real, and it is what makes the ``UNVERIFIABLE`` verdict on
    "500 finished units" honest rather than staged.
    """
    rng = random.Random(seed)
    img = Image.new("RGB", size, (34, 34, 38))
    draw = ImageDraw.Draw(img)

    # rail
    draw.rectangle([0, int(size[1] * 0.13), size[0], int(size[1] * 0.15)], fill=(96, 96, 104))

    slot = size[0] / max(1, garments)
    for i in range(garments):
        x = slot * i + slot * 0.12
        w = slot * 0.72
        top = size[1] * 0.15
        bottom = size[1] * (0.72 + rng.random() * 0.12)
        jitter = tuple(max(0, min(255, ch + rng.randint(-9, 9))) for ch in colour)
        draw.polygon(
            [
                (x + w * 0.5, top),
                (x + w, top + (bottom - top) * 0.18),
                (x + w * 0.86, bottom),
                (x + w * 0.14, bottom),
                (x, top + (bottom - top) * 0.18),
            ],
            fill=jitter,
        )
        draw.line(
            [(x + w * 0.5, top), (x + w * 0.5, bottom)],
            fill=tuple(max(0, ch - 26) for ch in jitter),
            width=2,
        )

    # floor
    draw.rectangle([0, int(size[1] * 0.86), size[0], size[1]], fill=(52, 52, 58))
    if blur > 0:
        img = img.filter(ImageFilter.GaussianBlur(radius=blur))

    buffer = io.BytesIO()
    img.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def render_spec_sheet(item_code: str, colour_hex: str) -> bytes:
    return render_pdf(
        DocSpec(
            kind="SPEC_REFERENCE",
            fields={
                "item_code": item_code,
                "colour": colour_hex,
                "fabric": "cotton 240 gsm",
                "approved_by": "Meridian Label design",
                "date": dt.date(2026, 8, 1).isoformat(),
            },
            line_items=[],
        )
    )


def iso(day: dt.date) -> str:
    return day.isoformat()
