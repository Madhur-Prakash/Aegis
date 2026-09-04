"""Deterministic synthetic corpus (spec 29).

    python -m scripts.generate_dataset --seed 42

Produces, all reproducibly:

* ``data/generated/deals.parquet``      2,000 deals with outcomes and train/valid/test splits
* ``data/generated/evidence/``          150 labelled bundles with real PDFs and PNGs
* ``data/generated/calibration/``       a SEPARATE corpus (seed 43) used to fit the
                                        confidence calibration, so the 150
                                        evaluation bundles are never touched by fitting
* ``data/generated/counterparties.json`` 30 entities, 4 of them thin-file
* ``data/fixtures/demo_deal.json``      the exact demo deal, so ``make demo`` is reproducible

Every base rate is declared in ``docs/DATA.md``, marked [sourced] or [assumed].
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import random
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from scripts.docgen import IVORY, DocSpec, render_pdf, render_photo, render_spec_sheet

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "generated"
FIXTURES = ROOT / "data" / "fixtures"

CATEGORIES = ("apparel", "electronics", "industrial", "agri", "services", "packaging")
IVORY_HEX = "#{:02x}{:02x}{:02x}".format(*IVORY)

# ── Declared base rates (see docs/DATA.md) ──────────────────────────────────
BASE_DISPUTE_RATE = 0.11  # [assumed] conservative: higher than most B2B escrow reports
THIN_FILE_SHARE = 0.18  # [assumed]
ON_TIME_MEAN = 0.88  # [assumed]
STRETCH_RISK_KNEE = 1.5  # [assumed] deals above 1.5x a seller's largest are riskier


# ─────────────────────────────────────────────────────────────────────────────
# Deals for the risk model
# ─────────────────────────────────────────────────────────────────────────────
@dataclass(slots=True)
class DealRow:
    deal_id: str
    category: str
    deals_completed: int
    gmv_paise: int
    disputes_raised: int
    on_time_rate: float
    largest_deal_paise: int
    deal_paise: int
    milestone_count: int
    counterparty_age_days: int
    condition_objectivity_score: float
    stretch_ratio: float
    dispute_rate: float
    log_gmv: float
    avg_milestone_paise: float
    category_code: int
    deal_went_bad: int
    split: str


def _bad_probability(
    *,
    deals_completed: int,
    dispute_rate: float,
    on_time_rate: float,
    stretch_ratio: float,
    objectivity: float,
    age_days: int,
    milestone_count: int,
) -> float:
    """The generative model behind ``deal_went_bad``.

    It is a smooth function of the features, not a lookup, so the risk model has
    something real to learn and the logistic baseline is a fair comparison.
    """
    # Terms are centred on the corpus means so the intercept alone sets the base
    # rate; docs/DATA.md declares the resulting rate as [assumed] and why.
    z = -1.30
    z += -0.045 * min(deals_completed, 40)
    z += 2.2 * dispute_rate
    z += -1.2 * (on_time_rate - ON_TIME_MEAN)
    z += 0.55 * max(0.0, stretch_ratio - STRETCH_RISK_KNEE)
    z += -1.3 * (objectivity - 0.60)
    z += -0.0009 * min(age_days, 1200)
    z += -0.06 * (min(milestone_count, 8) - 3)
    return 1.0 / (1.0 + math.exp(-z))


def generate_deals(seed: int, n: int = 2000) -> list[DealRow]:
    rng = random.Random(seed)
    rows: list[DealRow] = []
    for i in range(n):
        thin = rng.random() < THIN_FILE_SHARE
        deals_completed = 0 if thin else rng.randint(1, 45)
        age_days = rng.randint(5, 60) if thin else rng.randint(90, 1600)
        largest = 0 if deals_completed == 0 else int(rng.uniform(50_000, 900_000) * 100)
        gmv = (
            0
            if deals_completed == 0
            else int(largest * rng.uniform(1.1, 4.0) * deals_completed / 3)
        )
        disputes = 0
        if deals_completed:
            disputes = sum(1 for _ in range(deals_completed) if rng.random() < BASE_DISPUTE_RATE)
        on_time = min(1.0, max(0.4, rng.gauss(ON_TIME_MEAN, 0.09))) if deals_completed else 0.85
        milestone_count = rng.choice([2, 3, 3, 3, 4, 4, 5, 6])
        deal_paise = int(rng.uniform(80_000, 1_400_000) * 100)
        objectivity = round(min(1.0, max(0.0, rng.gauss(0.62, 0.2))), 4)
        stretch = deal_paise / largest if largest else 3.0
        dispute_rate = disputes / deals_completed if deals_completed else 0.0

        p = _bad_probability(
            deals_completed=deals_completed,
            dispute_rate=dispute_rate,
            on_time_rate=on_time,
            stretch_ratio=min(10.0, stretch),
            objectivity=objectivity,
            age_days=age_days,
            milestone_count=milestone_count,
        )
        went_bad = 1 if rng.random() < p else 0

        # 70 / 15 / 15 by a deterministic hash of the index.
        bucket = (i * 2654435761) % 100
        split = "train" if bucket < 70 else ("valid" if bucket < 85 else "test")

        rows.append(
            DealRow(
                deal_id=f"SYN-{i:05d}",
                category=CATEGORIES[i % len(CATEGORIES)],
                deals_completed=deals_completed,
                gmv_paise=gmv,
                disputes_raised=disputes,
                on_time_rate=round(on_time, 4),
                largest_deal_paise=largest,
                deal_paise=deal_paise,
                milestone_count=milestone_count,
                counterparty_age_days=age_days,
                condition_objectivity_score=objectivity,
                stretch_ratio=round(min(10.0, stretch), 4),
                dispute_rate=round(dispute_rate, 4),
                log_gmv=round(math.log1p(gmv), 6),
                avg_milestone_paise=round(deal_paise / milestone_count, 2),
                category_code=CATEGORIES.index(CATEGORIES[i % len(CATEGORIES)]),
                deal_went_bad=went_bad,
                split=split,
            )
        )
    return rows


# ─────────────────────────────────────────────────────────────────────────────
# Counterparties
# ─────────────────────────────────────────────────────────────────────────────
def generate_counterparties(seed: int, n: int = 30) -> list[dict[str, Any]]:
    rng = random.Random(seed + 7)
    regions = (
        "Tiruppur, Tamil Nadu",
        "Ludhiana, Punjab",
        "Surat, Gujarat",
        "Bengaluru, Karnataka",
        "Noida, Uttar Pradesh",
        "Kolkata, West Bengal",
    )
    out: list[dict[str, Any]] = []
    for i in range(n):
        thin = i < 4  # exactly four thin-file cases
        completed = 0 if thin else rng.randint(3, 40)
        largest = 0 if thin else int(rng.uniform(120_000, 900_000) * 100)
        out.append(
            {
                "slug": f"counterparty-{i:02d}",
                "display_name": f"{'Tirupur' if i % 3 == 0 else 'Meridian' if i % 3 == 1 else 'Kalyan'} "
                f"{'Exports' if i % 2 else 'Works'} {i:02d}",
                "region": regions[i % len(regions)],
                "category": CATEGORIES[i % len(CATEGORIES)],
                "thin_file": thin,
                "deals_completed": completed,
                "gmv_paise": 0 if thin else int(largest * rng.uniform(1.5, 5.0)),
                "disputes_raised": 0
                if thin
                else sum(1 for _ in range(completed) if rng.random() < BASE_DISPUTE_RATE),
                "disputes_lost": 0,
                "on_time_rate": 0.85
                if thin
                else round(min(1.0, max(0.5, rng.gauss(ON_TIME_MEAN, 0.08))), 4),
                "largest_deal_paise": largest,
                "counterparty_age_days": rng.randint(4, 45) if thin else rng.randint(180, 1500),
            }
        )
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Evidence bundles
# ─────────────────────────────────────────────────────────────────────────────
WINDOW_FROM = dt.date(2026, 8, 15)
WINDOW_TO = dt.date(2026, 9, 10)


def _condition_fabric(min_qty: float = 520.0, code: str = "CT-240-IVY") -> dict[str, Any]:
    return {
        "clauses": [
            {
                "id": "c1",
                "kind": "ARTIFACT_PRESENT",
                "description": "Supplier invoice present and readable",
                "params": {"artifact_types": ["INVOICE"], "min_count": 1},
                "required": True,
            },
            {
                "id": "c2",
                "kind": "ARTIFACT_PRESENT",
                "description": "Goods receipt note present and readable",
                "params": {"artifact_types": ["GRN"], "min_count": 1},
                "required": True,
            },
            {
                "id": "c3",
                "kind": "FIELD_EQUALS",
                "description": f"Fabric code is {code}",
                "params": {
                    "field": "item_code",
                    "value": code,
                    "artifact_types": ["INVOICE", "GRN"],
                },
                "required": True,
            },
            {
                "id": "c4",
                "kind": "QUANTITY_AT_LEAST",
                "description": f"Quantity received is at least {min_qty:g} m",
                "params": {
                    "field": "quantity",
                    "min": min_qty,
                    "artifact_types": ["GRN", "INVOICE"],
                },
                "required": True,
            },
            {
                "id": "c5",
                "kind": "DATE_WITHIN",
                "description": f"Dated between {WINDOW_FROM} and {WINDOW_TO}",
                "params": {
                    "field": "date",
                    "from": WINDOW_FROM.isoformat(),
                    "to": WINDOW_TO.isoformat(),
                    "artifact_types": ["INVOICE", "GRN"],
                },
                "required": True,
            },
        ],
        "required_artifact_types": ["INVOICE", "GRN"],
        "tolerance": {},
    }


def _condition_production(units: int = 500, code: str = "CT-240-IVY") -> dict[str, Any]:
    return {
        "clauses": [
            {
                "id": "c1",
                "kind": "ARTIFACT_PRESENT",
                "description": "Photo set present and legible",
                "params": {"artifact_types": ["PHOTO_SET"], "min_count": 4},
                "required": True,
            },
            {
                "id": "c2",
                "kind": "QUANTITY_AT_LEAST",
                "description": f"{units} finished units evidenced",
                "params": {
                    "field": "unit_count",
                    "min": float(units),
                    "artifact_types": ["PHOTO_SET"],
                },
                "required": True,
            },
            {
                "id": "c3",
                "kind": "VISUAL_CONSISTENT_WITH",
                "description": f"Matches approved specification {code}",
                "params": {"colour": IVORY_HEX, "tolerance": 60, "artifact_types": ["PHOTO_SET"]},
                "required": True,
            },
        ],
        "required_artifact_types": ["PHOTO_SET", "SPEC_REFERENCE"],
        "tolerance": {},
    }


def _condition_delivery() -> dict[str, Any]:
    return {
        "clauses": [
            {
                "id": "c1",
                "kind": "ARTIFACT_PRESENT",
                "description": "Signed delivery challan present",
                "params": {"artifact_types": ["DELIVERY_CHALLAN"], "min_count": 1},
                "required": True,
            },
            {
                "id": "c2",
                "kind": "ARTIFACT_PRESENT",
                "description": "Condition report present",
                "params": {"artifact_types": ["CONDITION_REPORT"], "min_count": 1},
                "required": True,
            },
            {
                "id": "c3",
                "kind": "FIELD_MATCHES_SPEC",
                "description": "Challan carries a signatory",
                "params": {
                    "field": "signed_by",
                    "pattern": r".{3,}",
                    "artifact_types": ["DELIVERY_CHALLAN"],
                },
                "required": True,
            },
            {
                "id": "c4",
                "kind": "DATE_WITHIN",
                "description": f"Delivered between {WINDOW_FROM} and {WINDOW_TO}",
                "params": {
                    "field": "date",
                    "from": WINDOW_FROM.isoformat(),
                    "to": WINDOW_TO.isoformat(),
                    "artifact_types": ["DELIVERY_CHALLAN"],
                },
                "required": True,
            },
        ],
        "required_artifact_types": ["DELIVERY_CHALLAN", "CONDITION_REPORT"],
        "tolerance": {},
    }


def _condition_amount(minimum_rupees: float = 100_000.0) -> dict[str, Any]:
    return {
        "clauses": [
            {
                "id": "c1",
                "kind": "ARTIFACT_PRESENT",
                "description": "Invoice present",
                "params": {"artifact_types": ["INVOICE"], "min_count": 1},
                "required": True,
            },
            {
                "id": "c2",
                "kind": "AMOUNT_AT_LEAST",
                "description": f"Invoice total is at least INR {minimum_rupees:,.0f}",
                "params": {
                    "field": "total",
                    "min": minimum_rupees,
                    "artifact_types": ["INVOICE"],
                },
                "required": True,
            },
            {
                "id": "c3",
                "kind": "DATE_WITHIN",
                "description": f"Dated between {WINDOW_FROM} and {WINDOW_TO}",
                "params": {
                    "field": "date",
                    "from": WINDOW_FROM.isoformat(),
                    "to": WINDOW_TO.isoformat(),
                    "artifact_types": ["INVOICE"],
                },
                "required": True,
            },
        ],
        "required_artifact_types": ["INVOICE"],
        "tolerance": {},
    }


def _condition_qc(code: str = "CT-240-IVY") -> dict[str, Any]:
    return {
        "clauses": [
            {
                "id": "c1",
                "kind": "ARTIFACT_PRESENT",
                "description": "Condition report present",
                "params": {"artifact_types": ["CONDITION_REPORT"], "min_count": 1},
                "required": True,
            },
            {
                "id": "c2",
                "kind": "FIELD_EQUALS",
                "description": f"Item code is {code}",
                "params": {
                    "field": "item_code",
                    "value": code,
                    "artifact_types": ["CONDITION_REPORT"],
                },
                "required": True,
            },
            {
                "id": "c3",
                "kind": "ARTIFACT_PRESENT",
                "description": "Supporting photographs present",
                "params": {"artifact_types": ["PHOTO_SET"], "min_count": 2},
                "required": False,
            },
        ],
        "required_artifact_types": ["CONDITION_REPORT"],
        "tolerance": {},
    }


MILESTONE_TYPES = {
    "fabric_procured": _condition_fabric,
    "production_complete": _condition_production,
    "delivered_accepted": _condition_delivery,
    "invoice_value": _condition_amount,
    "quality_check": _condition_qc,
}


@dataclass(slots=True)
class Bundle:
    bundle_id: str
    milestone_type: str
    label: str  # should_release | should_reject | should_escalate
    adversarial: str | None
    condition: dict[str, Any]
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    note: str = ""


def _invoice_doc(
    *,
    day: dt.date,
    code: str,
    quantity: float,
    unit_rate: float,
    total_override: float | None = None,
    degrade: bool = False,
    vendor: str = "Sri Textiles",
) -> DocSpec:
    amount = round(quantity * unit_rate, 2)
    return DocSpec(
        kind="INVOICE",
        fields={
            "vendor": vendor,
            "buyer": "Meridian Label",
            "invoice_no": f"SRI/{day.strftime('%Y%m')}/{int(quantity)}",
            "date": day.isoformat(),
            "currency": "INR",
            "item_code": code,
            "quantity": f"{quantity:g} m",
            "uom": "m",
        },
        line_items=[
            {
                "description": f"Cotton {code}",
                "quantity": f"{quantity:g}",
                "uom": "m",
                "amount": f"{amount:.2f}",
            }
        ],
        degrade=degrade,
        stated_total_override=total_override,
    )


def _grn_doc(*, day: dt.date, code: str, quantity: float, degrade: bool = False) -> DocSpec:
    return DocSpec(
        kind="GRN",
        fields={
            "ref_no": f"GRN-{day.strftime('%d%m')}-{int(quantity)}",
            "date": day.isoformat(),
            "item_code": code,
            "quantity": f"{quantity:g} m",
            "uom": "m",
            "signed_by": "Stores, Meridian Label",
        },
        line_items=[],
        degrade=degrade,
    )


def _challan_doc(*, day: dt.date, units: int, signed: bool = True) -> DocSpec:
    return DocSpec(
        kind="DELIVERY_CHALLAN",
        fields={
            "ref_no": f"DC-{day.strftime('%d%m')}-{units}",
            "date": day.isoformat(),
            "quantity": f"{units} pcs",
            "uom": "pcs",
            "signed_by": "R. Krishnan, Meridian Label warehouse" if signed else None,
        },
        line_items=[],
    )


def _condition_doc(*, day: dt.date, code: str, condition: str, units: int) -> DocSpec:
    return DocSpec(
        kind="CONDITION_REPORT",
        fields={
            "date": day.isoformat(),
            "item_code": code,
            "unit_count": str(units),
            "condition": condition,
            "signed_by": "QC, Meridian Label",
        },
        line_items=[],
    )


def _artifact(kind: str, filename: str, payload: bytes, mime: str) -> dict[str, Any]:
    return {"artifact_type": kind, "filename": filename, "mime": mime, "bytes": payload}


def _photo_set(seed: int, *, count: int = 4, colour=IVORY, blur: float = 0.0, size=(1280, 960)):
    return [
        _artifact(
            "PHOTO_SET",
            f"line-{i + 1:02d}.png",
            render_photo(seed=seed * 100 + i, colour=colour, blur=blur, size=size),
            "image/png",
        )
        for i in range(count)
    ]


ADVERSARIAL_KINDS = (
    "wrong_date",
    "altered_amount",
    "right_type_wrong_milestone",
    "fabricated_totals",
    "low_quality_scan",
    "photos_cannot_establish_quantity",
    "valid_but_unusual",
)


def build_bundle(index: int, rng: random.Random, *, prefix: str = "EB") -> Bundle:
    """One labelled bundle.

    Labels are derived from the *evidence*, following the same published rubric
    the system's prose prompt describes -- so a correct pipeline can reach them
    and an incorrect one cannot be rescued by the label.
    """
    milestone_type = list(MILESTONE_TYPES)[index % len(MILESTONE_TYPES)]
    bundle_id = f"{prefix}-{index:04d}"
    good_day = WINDOW_FROM + dt.timedelta(days=rng.randint(1, 20))
    bad_day = WINDOW_FROM - dt.timedelta(days=rng.randint(6, 40))
    code = "CT-240-IVY"

    # Every 3rd bundle is adversarial, which yields well over the required 40.
    adversarial = (
        ADVERSARIAL_KINDS[(index // 3) % len(ADVERSARIAL_KINDS)] if index % 3 == 0 else None
    )

    if milestone_type == "fabric_procured":
        condition = _condition_fabric()
        artifacts: list[dict[str, Any]] = []
        label = "should_release"
        note = "Invoice and GRN agree, code matches, quantity above the floor, dated in window."

        if adversarial == "wrong_date":
            artifacts += [
                _artifact(
                    "INVOICE",
                    "invoice.pdf",
                    render_pdf(_invoice_doc(day=bad_day, code=code, quantity=540, unit_rate=142.5)),
                    "application/pdf",
                ),
                _artifact(
                    "GRN",
                    "grn.pdf",
                    render_pdf(_grn_doc(day=bad_day, code=code, quantity=540)),
                    "application/pdf",
                ),
            ]
            label = "should_reject"
            note = "Correct document, wrong date: dated outside the agreed window."
        elif adversarial == "altered_amount":
            artifacts += [
                _artifact(
                    "INVOICE",
                    "invoice.pdf",
                    render_pdf(
                        _invoice_doc(day=good_day, code=code, quantity=410, unit_rate=142.5)
                    ),
                    "application/pdf",
                ),
                _artifact(
                    "GRN",
                    "grn.pdf",
                    render_pdf(_grn_doc(day=good_day, code=code, quantity=410)),
                    "application/pdf",
                ),
            ]
            label = "should_reject"
            note = "Quantity 410 m is below the 520 m floor."
        elif adversarial == "right_type_wrong_milestone":
            artifacts += [
                _artifact(
                    "INVOICE",
                    "invoice.pdf",
                    render_pdf(
                        _invoice_doc(day=good_day, code="CT-180-SLT", quantity=560, unit_rate=118.0)
                    ),
                    "application/pdf",
                ),
                _artifact(
                    "GRN",
                    "grn.pdf",
                    render_pdf(_grn_doc(day=good_day, code="CT-180-SLT", quantity=560)),
                    "application/pdf",
                ),
            ]
            label = "should_reject"
            note = "Right document type, wrong milestone: the fabric code is a different article."
        elif adversarial == "fabricated_totals":
            artifacts += [
                _artifact(
                    "INVOICE",
                    "invoice.pdf",
                    render_pdf(
                        _invoice_doc(
                            day=good_day,
                            code=code,
                            quantity=540,
                            unit_rate=142.5,
                            total_override=41_800.00,
                        )
                    ),
                    "application/pdf",
                ),
                _artifact(
                    "GRN",
                    "grn.pdf",
                    render_pdf(_grn_doc(day=good_day, code=code, quantity=540)),
                    "application/pdf",
                ),
            ]
            label = "should_escalate"
            note = (
                "The invoice's stated total does not equal the sum of its line items: "
                "internally inconsistent, and a human must look."
            )
        elif adversarial == "low_quality_scan":
            artifacts += [
                _artifact(
                    "INVOICE",
                    "invoice-scan.pdf",
                    render_pdf(
                        _invoice_doc(
                            day=good_day, code=code, quantity=540, unit_rate=142.5, degrade=True
                        )
                    ),
                    "application/pdf",
                ),
                _artifact(
                    "GRN",
                    "grn.pdf",
                    render_pdf(_grn_doc(day=good_day, code=code, quantity=540)),
                    "application/pdf",
                ),
            ]
            label = "should_escalate"
            note = "The invoice is an unreadable scan; its fields cannot be checked either way."
        elif adversarial == "valid_but_unusual":
            artifacts += [
                _artifact(
                    "INVOICE",
                    "invoice.pdf",
                    render_pdf(
                        _invoice_doc(
                            day=good_day,
                            code=code,
                            quantity=2400,
                            unit_rate=142.5,
                            vendor="Sri Textiles (consolidated shipment)",
                        )
                    ),
                    "application/pdf",
                ),
                _artifact(
                    "GRN",
                    "grn.pdf",
                    render_pdf(_grn_doc(day=good_day, code=code, quantity=2400)),
                    "application/pdf",
                ),
            ]
            label = "should_release"
            note = "Perfectly valid but unusual: a single consolidated 2,400 m shipment."
        else:
            qty = 520 + rng.randint(0, 90)
            artifacts += [
                _artifact(
                    "INVOICE",
                    "invoice.pdf",
                    render_pdf(
                        _invoice_doc(day=good_day, code=code, quantity=qty, unit_rate=142.5)
                    ),
                    "application/pdf",
                ),
                _artifact(
                    "GRN",
                    "grn.pdf",
                    render_pdf(_grn_doc(day=good_day, code=code, quantity=qty)),
                    "application/pdf",
                ),
            ]

        if adversarial == "photos_cannot_establish_quantity":
            # A photo set submitted in place of the paperwork: the required
            # artifact types are simply absent, so this is a zero-token REJECT.
            artifacts = _photo_set(index, count=4)
            label = "should_reject"
            note = "A required artifact type was not submitted at all."

        return Bundle(bundle_id, milestone_type, label, adversarial, condition, artifacts, note)

    if milestone_type == "production_complete":
        condition = _condition_production()
        spec = _artifact(
            "SPEC_REFERENCE", "spec.pdf", render_spec_sheet(code, IVORY_HEX), "application/pdf"
        )
        # The default case for this milestone type is ESCALATE, and that is the
        # honest answer: photographs cannot establish a count of 500.
        if adversarial == "valid_but_unusual":
            artifacts = [*_photo_set(index, count=8, size=(1600, 1200)), spec]
            label = "should_escalate"
            note = (
                "Eight high-resolution photographs, all matching the approved colour -- and still "
                "no evidence of a count of 500."
            )
        elif adversarial == "low_quality_scan":
            artifacts = [*_photo_set(index, count=4, blur=6.0, size=(320, 240)), spec]
            label = "should_escalate"
            note = "Blurred, low-resolution photographs: neither the colour nor the count is checkable."
        elif adversarial == "right_type_wrong_milestone":
            artifacts = [*_photo_set(index, count=4, colour=(58, 92, 168)), spec]
            label = "should_reject"
            note = (
                "The photographed garments are a different colour from the approved specification."
            )
        elif adversarial == "photos_cannot_establish_quantity":
            artifacts = [*_photo_set(index, count=4), spec]
            label = "should_escalate"
            note = "Four photographs cannot establish a count of 500 finished units."
        elif adversarial == "wrong_date":
            artifacts = [*_photo_set(index, count=2), spec]
            label = "should_reject"
            note = "Only two photographs were submitted; the clause requires at least four."
        else:
            artifacts = [*_photo_set(index, count=4), spec]
            label = "should_escalate"
            note = "Four photographs cannot establish a count of 500 finished units."
        return Bundle(bundle_id, milestone_type, label, adversarial, condition, artifacts, note)

    if milestone_type == "delivered_accepted":
        condition = _condition_delivery()
        if adversarial == "wrong_date":
            artifacts = [
                _artifact(
                    "DELIVERY_CHALLAN",
                    "challan.pdf",
                    render_pdf(_challan_doc(day=bad_day, units=500)),
                    "application/pdf",
                ),
                _artifact(
                    "CONDITION_REPORT",
                    "condition.pdf",
                    render_pdf(
                        _condition_doc(day=bad_day, code=code, condition="accepted", units=500)
                    ),
                    "application/pdf",
                ),
            ]
            label = "should_reject"
            note = "Delivered outside the agreed window."
        elif adversarial == "altered_amount":
            artifacts = [
                _artifact(
                    "DELIVERY_CHALLAN",
                    "challan.pdf",
                    render_pdf(_challan_doc(day=good_day, units=500, signed=False)),
                    "application/pdf",
                ),
                _artifact(
                    "CONDITION_REPORT",
                    "condition.pdf",
                    render_pdf(
                        _condition_doc(day=good_day, code=code, condition="accepted", units=500)
                    ),
                    "application/pdf",
                ),
            ]
            label = "should_escalate"
            note = "The challan carries no signatory, so acceptance cannot be established."
        elif adversarial == "low_quality_scan":
            artifacts = [
                _artifact(
                    "DELIVERY_CHALLAN",
                    "challan-scan.pdf",
                    render_pdf(
                        DocSpec(
                            kind="DELIVERY_CHALLAN",
                            fields={
                                "ref_no": "DC-scan",
                                "date": good_day.isoformat(),
                                "signed_by": "illegible",
                            },
                            line_items=[],
                            degrade=True,
                        )
                    ),
                    "application/pdf",
                ),
                _artifact(
                    "CONDITION_REPORT",
                    "condition.pdf",
                    render_pdf(
                        _condition_doc(day=good_day, code=code, condition="accepted", units=500)
                    ),
                    "application/pdf",
                ),
            ]
            label = "should_escalate"
            note = "The challan is an unreadable scan."
        elif adversarial == "right_type_wrong_milestone":
            artifacts = [
                _artifact(
                    "DELIVERY_CHALLAN",
                    "challan.pdf",
                    render_pdf(_challan_doc(day=good_day, units=500)),
                    "application/pdf",
                ),
            ]
            label = "should_reject"
            note = "The condition report, a required artifact type, is missing."
        else:
            artifacts = [
                _artifact(
                    "DELIVERY_CHALLAN",
                    "challan.pdf",
                    render_pdf(_challan_doc(day=good_day, units=500)),
                    "application/pdf",
                ),
                _artifact(
                    "CONDITION_REPORT",
                    "condition.pdf",
                    render_pdf(
                        _condition_doc(day=good_day, code=code, condition="accepted", units=500)
                    ),
                    "application/pdf",
                ),
            ]
            label = "should_release"
            note = "Signed challan and a clean condition report, both dated in the window."
        return Bundle(bundle_id, milestone_type, label, adversarial, condition, artifacts, note)

    if milestone_type == "invoice_value":
        condition = _condition_amount(100_000.0)
        if adversarial == "altered_amount":
            artifacts = [
                _artifact(
                    "INVOICE",
                    "invoice.pdf",
                    render_pdf(
                        _invoice_doc(day=good_day, code=code, quantity=300, unit_rate=142.5)
                    ),
                    "application/pdf",
                )
            ]
            label = "should_reject"
            note = "Invoice total INR 42,750 is below the INR 100,000 floor."
        elif adversarial == "fabricated_totals":
            artifacts = [
                _artifact(
                    "INVOICE",
                    "invoice.pdf",
                    render_pdf(
                        _invoice_doc(
                            day=good_day,
                            code=code,
                            quantity=800,
                            unit_rate=142.5,
                            total_override=118_000.00,
                        )
                    ),
                    "application/pdf",
                )
            ]
            label = "should_escalate"
            note = "The stated total does not match the line items."
        elif adversarial == "wrong_date":
            artifacts = [
                _artifact(
                    "INVOICE",
                    "invoice.pdf",
                    render_pdf(_invoice_doc(day=bad_day, code=code, quantity=800, unit_rate=142.5)),
                    "application/pdf",
                )
            ]
            label = "should_reject"
            note = "Dated outside the window."
        elif adversarial == "low_quality_scan":
            artifacts = [
                _artifact(
                    "INVOICE",
                    "invoice-scan.pdf",
                    render_pdf(
                        _invoice_doc(
                            day=good_day, code=code, quantity=800, unit_rate=142.5, degrade=True
                        )
                    ),
                    "application/pdf",
                )
            ]
            label = "should_escalate"
            note = "Unreadable scan: neither the amount nor the date is checkable."
        else:
            artifacts = [
                _artifact(
                    "INVOICE",
                    "invoice.pdf",
                    render_pdf(
                        _invoice_doc(
                            day=good_day,
                            code=code,
                            quantity=750 + rng.randint(0, 200),
                            unit_rate=142.5,
                        )
                    ),
                    "application/pdf",
                )
            ]
            label = "should_release"
            note = "Invoice total above the floor, dated in the window."
        return Bundle(bundle_id, milestone_type, label, adversarial, condition, artifacts, note)

    # quality_check
    condition = _condition_qc()
    if adversarial == "right_type_wrong_milestone":
        artifacts = [
            _artifact(
                "CONDITION_REPORT",
                "condition.pdf",
                render_pdf(
                    _condition_doc(day=good_day, code="CT-180-SLT", condition="accepted", units=500)
                ),
                "application/pdf",
            )
        ]
        label = "should_reject"
        note = "The condition report references a different item code."
    elif adversarial == "low_quality_scan":
        artifacts = [
            _artifact(
                "CONDITION_REPORT",
                "condition-scan.pdf",
                render_pdf(
                    DocSpec(
                        kind="CONDITION_REPORT",
                        fields={"date": good_day.isoformat()},
                        line_items=[],
                        degrade=True,
                    )
                ),
                "application/pdf",
            )
        ]
        label = "should_escalate"
        note = "Unreadable scan: the item code cannot be compared."
    elif adversarial == "valid_but_unusual":
        artifacts = [
            _artifact(
                "CONDITION_REPORT",
                "condition.pdf",
                render_pdf(
                    _condition_doc(
                        day=good_day,
                        code=code,
                        condition="accepted with 3 units re-stitched at source before dispatch",
                        units=500,
                    )
                ),
                "application/pdf",
            ),
            *_photo_set(index, count=2),
        ]
        label = "should_release"
        note = "Valid but unusual wording; the required clauses are all satisfied."
    else:
        artifacts = [
            _artifact(
                "CONDITION_REPORT",
                "condition.pdf",
                render_pdf(
                    _condition_doc(day=good_day, code=code, condition="accepted", units=500)
                ),
                "application/pdf",
            ),
            *_photo_set(index, count=2),
        ]
        label = "should_release"
        note = "Condition report present with the correct item code."
    return Bundle(bundle_id, milestone_type, label, adversarial, condition, artifacts, note)


def write_bundles(target: Path, seed: int, count: int, prefix: str) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)
    manifest: list[dict[str, Any]] = []
    for i in range(count):
        bundle = build_bundle(i, rng, prefix=prefix)
        folder = target / bundle.bundle_id
        folder.mkdir(parents=True, exist_ok=True)
        entries = []
        for artifact in bundle.artifacts:
            path = folder / artifact["filename"]
            path.write_bytes(artifact["bytes"])
            entries.append(
                {
                    "artifact_type": artifact["artifact_type"],
                    "filename": artifact["filename"],
                    "mime": artifact["mime"],
                    "size_bytes": len(artifact["bytes"]),
                }
            )
        record = {
            "bundle_id": bundle.bundle_id,
            "milestone_type": bundle.milestone_type,
            "label": bundle.label,
            "adversarial": bundle.adversarial,
            "note": bundle.note,
            "condition": bundle.condition,
            "artifacts": entries,
            "path": str(folder.relative_to(target.parent)),
        }
        (folder / "bundle.json").write_text(
            json.dumps(record, indent=2, sort_keys=True), encoding="utf-8"
        )
        manifest.append(record)
    (target / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
    )
    return manifest


# ─────────────────────────────────────────────────────────────────────────────
# Demo fixture
# ─────────────────────────────────────────────────────────────────────────────
UNIT_PRICE_PAISE = 84_000  # INR 840 per kurta
DEMO_UNITS = 500
DEMO_TOTAL_PAISE = 42_000_000  # INR 4,20,000


def demo_fixture() -> dict[str, Any]:
    return {
        "reference": "D-4812",
        "title": "500 custom kurtas",
        "category": "apparel",
        "total_paise": DEMO_TOTAL_PAISE,
        "dispute_window_days": 7,
        "buyer": {
            "org_name": "Meridian Label",
            "slug": "meridian-label",
            "city": "Bengaluru",
            "entity_name": "Meridian Label Procurement",
            "region": "Bengaluru, Karnataka",
            "owner_email": "owner@meridian.demo",
            "owner_name": "Aditi Rao",
        },
        "seller": {
            "org_name": "Tirupur Exports",
            "slug": "tirupur-exports",
            "city": "Tiruppur",
            "entity_name": "Tirupur Exports Manufacturing",
            "region": "Tiruppur, Tamil Nadu",
            "owner_email": "owner@tirupur.demo",
            "owner_name": "S. Murugan",
        },
        "seller_profile": {
            "deals_completed": 11,
            "gmv_paise": 314_000_000,
            "disputes_raised": 1,
            "disputes_lost": 0,
            "on_time_rate": 0.91,
            "largest_deal_paise": 62_000_000,
            "category": "apparel",
            "counterparty_since": "2025-03-14",
        },
        "tolerance": {
            "total_units": DEMO_UNITS,
            "unit_price_paise": UNIT_PRICE_PAISE,
            "variance_deduction_pct": 20,
            "clause_ids": ["t1"],
            "description": (
                "Colour variance beyond the approved swatch attracts a 20% deduction per "
                "affected unit."
            ),
        },
        "milestones": [
            {
                "seq": 1,
                "title": "Fabric procured",
                "amount_paise": 12_600_000,
                "verification_condition": _condition_fabric(),
                "evidence": "fabric",
            },
            {
                "seq": 2,
                "title": "Production complete",
                "amount_paise": 16_800_000,
                "verification_condition": _condition_production(),
                "evidence": "production",
            },
            {
                "seq": 3,
                "title": "Delivered & accepted",
                "amount_paise": 12_600_000,
                "verification_condition": _condition_delivery(),
                "evidence": "delivery",
            },
        ],
        "expected_narrative": {
            "milestone_1": "all required clauses PASS -> RELEASE, INR 1,26,000 settles",
            "milestone_2": (
                "the '500 finished units' clause returns UNVERIFIABLE -> ESCALATE, no money moves, "
                "human review appears"
            ),
            "milestone_3": (
                "buyer disputes 60 of 500 units for colour variance; the arbiter applies the "
                "tolerance clause (60 x 84000 paise x 20% = 1008000 paise) and recommends "
                "PARTIAL: release 11592000 / refund 1008000; a human approves"
            ),
            "note": (
                "These outcomes are produced by the real pipeline. No milestone is special-cased. "
                "The measured confidence values are written by `make eval` and `make demo`."
            ),
        },
    }


def write_demo_evidence(target: Path) -> dict[str, Any]:
    """The exact artifacts the demo deal's three milestones use."""
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)
    day = dt.date(2026, 8, 28)
    code = "CT-240-IVY"
    manifest: dict[str, Any] = {}

    fabric = target / "fabric"
    fabric.mkdir(parents=True, exist_ok=True)
    (fabric / "invoice-ct240.pdf").write_bytes(
        render_pdf(_invoice_doc(day=day, code=code, quantity=540, unit_rate=142.5))
    )
    (fabric / "grn-ct240.pdf").write_bytes(render_pdf(_grn_doc(day=day, code=code, quantity=540)))
    manifest["fabric"] = [
        {"artifact_type": "INVOICE", "filename": "invoice-ct240.pdf", "mime": "application/pdf"},
        {"artifact_type": "GRN", "filename": "grn-ct240.pdf", "mime": "application/pdf"},
    ]

    production = target / "production"
    production.mkdir(parents=True, exist_ok=True)
    for i in range(4):
        (production / f"line-{i + 1:02d}.png").write_bytes(
            render_photo(seed=4812 + i, colour=IVORY)
        )
    (production / "spec-ct240.pdf").write_bytes(render_spec_sheet(code, IVORY_HEX))
    manifest["production"] = [
        {"artifact_type": "PHOTO_SET", "filename": f"line-{i + 1:02d}.png", "mime": "image/png"}
        for i in range(4)
    ] + [
        {"artifact_type": "SPEC_REFERENCE", "filename": "spec-ct240.pdf", "mime": "application/pdf"}
    ]

    delivery = target / "delivery"
    delivery.mkdir(parents=True, exist_ok=True)
    delivered = dt.date(2026, 9, 3)
    (delivery / "challan-4812.pdf").write_bytes(
        render_pdf(_challan_doc(day=delivered, units=DEMO_UNITS))
    )
    (delivery / "condition-4812.pdf").write_bytes(
        render_pdf(
            _condition_doc(
                day=delivered,
                code=code,
                condition="accepted, 60 units flagged for colour variance by the buyer",
                units=DEMO_UNITS,
            )
        )
    )
    manifest["delivery"] = [
        {
            "artifact_type": "DELIVERY_CHALLAN",
            "filename": "challan-4812.pdf",
            "mime": "application/pdf",
        },
        {
            "artifact_type": "CONDITION_REPORT",
            "filename": "condition-4812.pdf",
            "mime": "application/pdf",
        },
    ]
    (target / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
    )
    return manifest


# ─────────────────────────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(description="Generate the Aegis synthetic corpus")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--deals", type=int, default=2000)
    parser.add_argument("--bundles", type=int, default=150)
    parser.add_argument("--calibration-bundles", type=int, default=120)
    args = parser.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    FIXTURES.mkdir(parents=True, exist_ok=True)

    rows = generate_deals(args.seed, args.deals)
    try:
        import pandas as pd

        frame = pd.DataFrame([asdict(r) for r in rows])
        frame.to_parquet(OUT / "deals.parquet", index=False)
        for split in ("train", "valid", "test"):
            frame[frame["split"] == split].to_parquet(OUT / f"deals_{split}.parquet", index=False)
        print(
            f"deals.parquet: {len(frame)} rows "
            f"(train {int((frame['split'] == 'train').sum())} / "
            f"valid {int((frame['split'] == 'valid').sum())} / "
            f"test {int((frame['split'] == 'test').sum())}), "
            f"bad rate {frame['deal_went_bad'].mean():.4f}"
        )
    except Exception as exc:  # pragma: no cover
        print(f"parquet write failed ({type(exc).__name__}); writing JSONL instead")
        (OUT / "deals.jsonl").write_text(
            "\n".join(json.dumps(asdict(r)) for r in rows), encoding="utf-8"
        )

    counterparties = generate_counterparties(args.seed)
    (OUT / "counterparties.json").write_text(
        json.dumps(counterparties, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(
        f"counterparties.json: {len(counterparties)} entities, "
        f"{sum(1 for c in counterparties if c['thin_file'])} thin-file"
    )

    manifest = write_bundles(OUT / "evidence", args.seed, args.bundles, "EB")
    adversarial = sum(1 for m in manifest if m["adversarial"])
    labels: dict[str, int] = {}
    for m in manifest:
        labels[m["label"]] = labels.get(m["label"], 0) + 1
    print(f"evidence/: {len(manifest)} bundles, {adversarial} adversarial, labels {labels}")

    # A SEPARATE corpus, different seed, used only to fit the calibration map.
    calib = write_bundles(OUT / "calibration", args.seed + 1, args.calibration_bundles, "CB")
    print(f"calibration/: {len(calib)} bundles (never used for evaluation)")

    (FIXTURES / "demo_deal.json").write_text(
        json.dumps(demo_fixture(), indent=2, sort_keys=True), encoding="utf-8"
    )
    demo_manifest = write_demo_evidence(FIXTURES / "demo_evidence")
    print(
        f"demo_deal.json + demo_evidence/: {sum(len(v) for v in demo_manifest.values())} artifacts"
    )


if __name__ == "__main__":
    main()
