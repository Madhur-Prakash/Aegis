"""Structured-output schemas for the verifier.  Pydantic v2, used verbatim as the
``output_format`` for every provider."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ExtractedInvoice(BaseModel):
    vendor: str | None = None
    invoice_no: str | None = None
    date: str | None = None
    currency: str | None = None
    total_paise: int | None = None
    item_code: str | None = None
    quantity: float | None = None
    uom: str | None = None
    line_items: list[dict] = Field(default_factory=list)
    internally_consistent: bool | None = None
    note: str = ""


class ExtractedGRN(BaseModel):
    ref_no: str | None = None
    date: str | None = None
    item_code: str | None = None
    quantity: float | None = None
    uom: str | None = None
    note: str = ""


class ExtractedPhotoSet(BaseModel):
    visible_item_count_estimate: int | None = None
    count_establishable: bool = False
    colour_summary: str | None = None
    defects_noted: list[str] = Field(default_factory=list)
    legible: bool = True
    note: str = ""


class ExtractedDocument(BaseModel):
    """The generic extraction envelope, used for every artifact type."""

    artifact_id: str
    artifact_type: str
    fields: dict = Field(default_factory=dict)
    unreadable_fields: list[str] = Field(default_factory=list)
    legible: bool = True
    note: str = ""


class ClauseVerdict(BaseModel):
    clause_id: str
    verdict: Literal["PASS", "FAIL", "UNVERIFIABLE"]
    evidence_refs: list[str] = Field(default_factory=list)
    clause_confidence: float = 0.0
    note: str = ""


class ClauseEvaluation(BaseModel):
    verdicts: list[ClauseVerdict] = Field(default_factory=list)
    overall_note: str = ""
