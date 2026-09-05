"""Deterministic content analysis of an artifact's bytes.

Runs before any model call, and its output is what the extraction prompt shows
the model.  Nothing here guesses: a PDF yields its real text layer, an image
yields real pixel statistics.

The image path is deliberately honest about its limits.  Pixel statistics can
establish that four photographs exist, are in focus and share a colour family.
They cannot establish that 500 finished units exist -- which is precisely why the
demo's milestone 2 reaches ``UNVERIFIABLE`` through the ordinary pipeline rather
than through a special case.
"""

from __future__ import annotations

import io
import math
import re
from dataclasses import dataclass, field
from typing import Any

from app.common.logging import get_logger

log = get_logger("evidence.analyse")

# Decompression-bomb ceilings.  Both formats let a small upload expand into an
# enormous amount of work, so the 20 MB size cap on the *file* says very little
# about the cost of reading it.
#
# A 40-megapixel photograph is already far beyond anything a phone produces for a
# packing shot, while Pillow's own default only *warns* at 89 MP and does not
# raise until twice that -- by which point ~500 MB has been allocated for the RGB
# buffer alone, before `convert`, `FIND_EDGES` and `resize` each want their own.
# A PNG that decompresses to that is a few tens of kilobytes on the wire.
MAX_IMAGE_PIXELS = 40_000_000
MAX_PDF_PAGES = 250


@dataclass(slots=True)
class Observation:
    """What deterministic inspection can say about one artifact."""

    parseable: bool
    kind: str  # pdf | image | text | unknown
    text: str = ""
    page_count: int = 0
    fields: dict[str, Any] = field(default_factory=dict)
    image: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        return {
            "parseable": self.parseable,
            "kind": self.kind,
            "page_count": self.page_count,
            "text_excerpt": self.text[:4000],
            "machine_readable_fields": self.fields,
            "image_analysis": self.image,
            "notes": self.notes,
        }


# ── PDF ─────────────────────────────────────────────────────────────────────
_LABEL_PATTERNS: tuple[tuple[str, str], ...] = (
    ("vendor", r"(?im)^\s*(?:vendor|supplier|seller|from)\s*[:\-]\s*(.+)$"),
    ("buyer", r"(?im)^\s*(?:buyer|bill to|consignee)\s*[:\-]\s*(.+)$"),
    ("invoice_no", r"(?im)^\s*(?:invoice\s*(?:no|number|#)|inv\s*no)\s*[:\-]\s*(\S+)"),
    ("ref_no", r"(?im)^\s*(?:grn|ref(?:erence)?\s*(?:no|number|#)?|challan\s*no)\s*[:\-]\s*(\S+)"),
    ("date", r"(?im)^\s*(?:date|dated|invoice date|grn date|delivery date)\s*[:\-]\s*(\S+)"),
    ("item_code", r"(?im)^\s*(?:item\s*code|fabric\s*code|sku|style\s*code)\s*[:\-]\s*(\S+)"),
    ("quantity", r"(?im)^\s*(?:quantity|qty|units)\s*[:\-]\s*([0-9][0-9,\.]*)\s*([a-zA-Z]*)"),
    ("uom", r"(?im)^\s*(?:uom|unit)\s*[:\-]\s*(\S+)"),
    ("currency", r"(?im)^\s*currency\s*[:\-]\s*(\S+)"),
    (
        "total",
        r"(?im)^\s*(?:total|grand total|amount|invoice total)\s*[:\-]\s*(?:INR|Rs\.?|₹)?\s*([0-9][0-9,\.]*)",
    ),
    ("condition", r"(?im)^\s*(?:condition|remarks|status)\s*[:\-]\s*(.+)$"),
    ("signed_by", r"(?im)^\s*(?:signed\s*by|received\s*by|authorised\s*by)\s*[:\-]\s*(.+)$"),
    ("unit_count", r"(?im)^\s*(?:unit\s*count|finished\s*units|pieces)\s*[:\-]\s*([0-9][0-9,\.]*)"),
)

_LINE_ITEM = re.compile(
    r"(?im)^\s*(?P<desc>[A-Za-z][A-Za-z0-9 \-/]{2,40}?)\s{2,}"
    r"(?P<qty>[0-9][0-9,\.]*)\s+(?P<uom>[A-Za-z]{1,6})\s+(?P<amount>[0-9][0-9,\.]*)\s*$"
)


def _to_number(raw: str) -> float | None:
    try:
        return float(raw.replace(",", "").strip())
    except (ValueError, AttributeError):
        return None


def analyse_pdf(data: bytes) -> Observation:
    obs = Observation(parseable=False, kind="pdf")
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        obs.page_count = len(reader.pages)
        pages = []
        # Text extraction is the expensive half, and page count is not bounded by
        # file size: a 20 MB PDF can declare tens of thousands of pages of
        # compressed content streams.  An invoice or a packing list is a handful
        # of pages, so read the first MAX_PDF_PAGES and say so rather than
        # handing an uploader an unbounded amount of the worker's CPU.
        for page in reader.pages[:MAX_PDF_PAGES]:
            try:
                pages.append(page.extract_text() or "")
            except Exception:
                pages.append("")
        if obs.page_count > MAX_PDF_PAGES:
            obs.notes.append(f"only the first {MAX_PDF_PAGES} of {obs.page_count} pages were read")
        obs.text = "\n".join(pages).strip()
        obs.parseable = bool(obs.text)
        if not obs.parseable:
            obs.notes.append("no extractable text layer")
    except Exception as exc:
        obs.notes.append(f"pdf parse failed: {type(exc).__name__}")
        return obs

    for name, pattern in _LABEL_PATTERNS:
        match = re.search(pattern, obs.text)
        if not match:
            continue
        value = match.group(1).strip()
        if name in {"quantity", "total", "unit_count"}:
            number = _to_number(value)
            if number is not None:
                obs.fields[name] = number
                if name == "quantity" and match.lastindex and match.lastindex >= 2:
                    unit = (match.group(2) or "").strip()
                    if unit:
                        obs.fields.setdefault("uom", unit)
        else:
            obs.fields[name] = value

    items = []
    for match in _LINE_ITEM.finditer(obs.text):
        items.append(
            {
                "description": match.group("desc").strip(),
                "quantity": _to_number(match.group("qty")),
                "uom": match.group("uom"),
                "amount": _to_number(match.group("amount")),
            }
        )
    if items:
        obs.fields["line_items"] = items
        total_of_items = sum(float(i["amount"] or 0) for i in items)
        obs.fields["line_items_sum"] = round(total_of_items, 2)
        stated = obs.fields.get("total")
        if stated is not None and abs(total_of_items - float(stated)) > 1.0:
            # Genuinely detected inconsistency: the fabricated-invoice adversarial case.
            obs.notes.append(
                f"internal inconsistency: line items sum to {total_of_items:.2f} "
                f"but the stated total is {float(stated):.2f}"
            )
            obs.fields["totals_consistent"] = False
        elif stated is not None:
            obs.fields["totals_consistent"] = True

    words = len(obs.text.split())
    obs.fields["word_count"] = words
    # A scan with almost no recoverable text is a legibility problem, not a fail.
    obs.fields["legible"] = words >= 12
    if words < 12:
        obs.notes.append("very little recoverable text -- likely a low-quality scan")
    return obs


_QUANTISE = 24  # bucket width per channel; coarse enough to survive compression noise
BACKDROP_LUMA = 70  # below this, a colour reads as studio backdrop rather than goods
BACKDROP_CHROMA = 26  # and with this little colour spread it is neutral


def _luma(rgb: list[int]) -> float:
    return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]


def _chroma(rgb: list[int]) -> int:
    return max(rgb) - min(rgb)


def _palette(rgb: Any, top: int = 6) -> list[dict[str, Any]]:
    """Quantised colour histogram of the frame, largest share first.

    Nothing is filtered out here: every colour is reported with its share, so a
    rule can ask "is the approved colour at least N% of the frame?" instead of
    trusting a single modal pixel.
    """
    small = rgb.resize((96, 96))
    counts: dict[tuple[int, int, int], int] = {}
    sums: dict[tuple[int, int, int], list[int]] = {}
    for pixel in small.getdata():
        key = (
            (pixel[0] // _QUANTISE) * _QUANTISE,
            (pixel[1] // _QUANTISE) * _QUANTISE,
            (pixel[2] // _QUANTISE) * _QUANTISE,
        )
        counts[key] = counts.get(key, 0) + 1
        bucket = sums.setdefault(key, [0, 0, 0])
        bucket[0] += pixel[0]
        bucket[1] += pixel[1]
        bucket[2] += pixel[2]
    total = sum(counts.values()) or 1
    ordered = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:top]
    out: list[dict[str, Any]] = []
    for key, count in ordered:
        mean = [round(sums[key][i] / count) for i in range(3)]
        out.append(
            {
                "rgb": mean,
                "hex": "#{:02x}{:02x}{:02x}".format(*tuple(mean)),
                "share": round(count / total, 4),
                "backdrop_like": bool(
                    _luma(mean) < BACKDROP_LUMA and _chroma(mean) < BACKDROP_CHROMA
                ),
            }
        )
    return out


def _subject_colour(palette: list[dict[str, Any]]) -> list[int]:
    """The largest-share colour that is not a neutral dark backdrop.

    A garment rail photographed against a dark studio wall has the wall as its
    most frequent colour.  Calling that "the colour of the goods" would be a
    plainly wrong reading of the evidence, so the backdrop is skipped -- and if
    every colour looks like backdrop the caller still gets the modal one, with
    the palette alongside it to show why.
    """
    for entry in palette:
        if not entry["backdrop_like"]:
            return list(entry["rgb"])
    return list(palette[0]["rgb"]) if palette else [0, 0, 0]


# ── Images ──────────────────────────────────────────────────────────────────
def analyse_image(data: bytes) -> Observation:
    obs = Observation(parseable=False, kind="image")
    try:
        from PIL import Image, ImageFilter, ImageStat

        # Pillow's own guard warns before it raises, and raises only at twice
        # this; refuse on the header instead, before a single pixel is decoded.
        Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS
        with Image.open(io.BytesIO(data)) as img:
            width, height = img.size
            if width * height > MAX_IMAGE_PIXELS:
                obs.notes.append(
                    f"image is {width}x{height}, beyond the {MAX_IMAGE_PIXELS:,}-pixel "
                    "budget, and was not decoded"
                )
                return obs
            img.load()
            rgb = img.convert("RGB")
            width, height = rgb.size
            stat = ImageStat.Stat(rgb)
            grey = rgb.convert("L")
            edges = grey.filter(ImageFilter.FIND_EDGES)
            edge_var = ImageStat.Stat(edges).var[0]
            colours: list[tuple[int, Any]] = rgb.resize((64, 64)).getcolors(maxcolors=64 * 64) or []
            dominant: tuple[int, int, int] = (
                tuple(max(colours, key=lambda c: c[0])[1]) if colours else (0, 0, 0)
            )

            # A photograph's single most frequent colour is usually its backdrop,
            # not its subject.  Reporting that as "the colour of the goods" would
            # be plainly wrong -- a garment rail shot against a dark studio wall
            # would read as dark.  So the analyser reports a quantised palette
            # with each entry's share of the frame, and the clause rubric asks
            # whether the approved colour is *present in quantity* rather than
            # whether it happens to be the modal pixel.
            palette = _palette(rgb)
            subject: list[int] = _subject_colour(palette) if palette else [int(c) for c in dominant]

            obs.parseable = True
            obs.image = {
                "width": width,
                "height": height,
                "megapixels": round(width * height / 1e6, 3),
                "mean_rgb": [round(v, 1) for v in stat.mean],
                "dominant_rgb": [int(c) for c in dominant],
                "dominant_hex": "#{:02x}{:02x}{:02x}".format(*dominant),
                "subject_rgb": subject,
                "subject_hex": "#{:02x}{:02x}{:02x}".format(*subject),
                "palette": palette,
                "distinct_colours_64px": len(colours),
                "edge_variance": round(edge_var, 1),
                "sharpness": "sharp" if edge_var > 180 else "soft" if edge_var > 40 else "blurred",
                "resolution_class": (
                    "high"
                    if width * height >= 1_000_000
                    else "low"
                    if width * height < 250_000
                    else "medium"
                ),
            }
            obs.fields = {
                # Nothing in a photograph establishes a total count of a batch.
                "visible_item_count_estimate": None,
                "count_establishable_from_pixels": False,
                "colour_summary": obs.image["subject_hex"],
                "colour_palette": palette,
                "legible": obs.image["sharpness"] != "blurred"
                and obs.image["resolution_class"] != "low",
                "defects_noted": [],
            }
            if obs.image["sharpness"] == "blurred":
                obs.fields["defects_noted"].append("image is blurred")
                obs.notes.append("blurred image: fields may not be recoverable")
            if obs.image["resolution_class"] == "low":
                obs.notes.append("low resolution")
            entropy_proxy = len(colours) / (64.0 * 64.0)
            obs.image["colour_entropy_proxy"] = round(entropy_proxy, 4)
    except Exception as exc:
        obs.notes.append(f"image parse failed: {type(exc).__name__}")
    return obs


def analyse_text(data: bytes) -> Observation:
    obs = Observation(parseable=True, kind="text")
    obs.text = data.decode("utf-8", errors="replace")
    obs.fields["word_count"] = len(obs.text.split())
    obs.fields["legible"] = obs.fields["word_count"] >= 8
    for name, pattern in _LABEL_PATTERNS:
        match = re.search(pattern, obs.text)
        if match:
            value = match.group(1).strip()
            obs.fields[name] = (
                _to_number(value) if name in {"quantity", "total", "unit_count"} else value
            )
    return obs


def analyse(data: bytes, mime: str) -> Observation:
    if mime == "application/pdf":
        return analyse_pdf(data)
    if mime.startswith("image/"):
        return analyse_image(data)
    if mime.startswith("text/"):
        return analyse_text(data)
    return Observation(parseable=False, kind="unknown", notes=[f"unsupported mime {mime}"])


def extraction_quality(obs: Observation, expected_fields: list[str]) -> float:
    """Field completeness and legibility, in [0, 1].  Never asked of the model."""
    if not obs.parseable:
        return 0.0
    present = sum(1 for f in expected_fields if obs.fields.get(f) not in (None, "", []))
    completeness = present / max(1, len(expected_fields))
    legible = 1.0 if obs.fields.get("legible", True) else 0.35
    if obs.kind == "image":
        # An image's ceiling is lower: pixel statistics are weak evidence of fields.
        sharp = {"sharp": 1.0, "soft": 0.7, "blurred": 0.3}.get(
            obs.image.get("sharpness", "soft"), 0.6
        )
        res = {"high": 1.0, "medium": 0.8, "low": 0.45}.get(
            obs.image.get("resolution_class", "medium"), 0.7
        )
        return round(min(1.0, 0.55 * sharp + 0.45 * res) * legible, 4)
    penalty = 0.85 if obs.notes else 1.0
    return round(min(1.0, 0.35 + 0.65 * completeness) * legible * penalty, 4)


def confidence_from_entropy(value: float) -> float:  # pragma: no cover - helper
    return 1.0 - math.exp(-3.0 * value)
