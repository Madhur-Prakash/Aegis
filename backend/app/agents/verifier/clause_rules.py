"""The clause rubric, as executable rules.

One implementation, used in two places:

* the **deterministic pre-check** stage decides which clauses are machine-checkable
  and resolves them at zero token cost;
* the **fixture provider** answers clause evaluation with the same rules, so an
  offline eval exercises the real rubric rather than a table of expected answers.

A live model (Anthropic or Groq) replaces only the *judgement*; the rubric it is
given in the system prompt is this one, written in prose.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from typing import Any

PASS = "PASS"
FAIL = "FAIL"
UNVERIFIABLE = "UNVERIFIABLE"

# Which clause kinds a deterministic checker can settle on its own, given the
# right field.  A visual clause never is.
DETERMINISTIC_KINDS = frozenset(
    {
        "ARTIFACT_PRESENT",
        "DATE_WITHIN",
        "AMOUNT_AT_LEAST",
        "QUANTITY_AT_LEAST",
        "FIELD_EQUALS",
        "FIELD_MATCHES_SPEC",
    }
)
PERCEPTUAL_KINDS = frozenset({"VISUAL_CONSISTENT_WITH"})


@dataclass(slots=True)
class RuleResult:
    verdict: str
    confidence: float
    note: str
    evidence_refs: list[str]
    deterministic: bool


def _parse_date(value: Any) -> dt.date | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d", "%d %b %Y", "%d %B %Y"):
        try:
            return dt.datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _number(value: Any) -> float | None:
    if value in (None, "", []):
        return None
    try:
        return float(str(value).replace(",", "").strip())
    except ValueError:
        return None


def _candidates(artifacts: list[dict[str, Any]], types: list[str] | None) -> list[dict[str, Any]]:
    if not types:
        return artifacts
    wanted = {t.upper() for t in types}
    return [a for a in artifacts if str(a.get("artifact_type", "")).upper() in wanted]


def _field(artifact: dict[str, Any], name: str) -> Any:
    fields = artifact.get("fields") or {}
    if name in fields:
        return fields[name]
    # A few well-known aliases, so a GRN's ``ref_no`` satisfies a clause written
    # against ``reference``.
    aliases = {
        "reference": ("ref_no", "invoice_no"),
        "amount": ("total", "total_paise"),
        "total_paise": ("total",),
        "code": ("item_code",),
        "units": ("unit_count", "quantity"),
    }
    for alias in aliases.get(name, ()):  # type: ignore[arg-type]
        if alias in fields:
            return fields[alias]
    return None


def _hex_to_rgb(value: str) -> tuple[int, int, int] | None:
    text = value.strip().lstrip("#")
    if len(text) != 6:
        return None
    try:
        return int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)
    except ValueError:
        return None


def evaluate_clause(clause: dict[str, Any], artifacts: list[dict[str, Any]]) -> RuleResult:
    kind = str(clause.get("kind", "")).upper()
    params = clause.get("params") or {}
    types = params.get("artifact_types") or clause.get("artifact_types")
    pool = _candidates(artifacts, types)

    if kind == "ARTIFACT_PRESENT":
        usable = [a for a in pool if a.get("parseable")]
        if usable:
            minimum = int(params.get("min_count", 1))
            if len(usable) >= minimum:
                return RuleResult(
                    PASS,
                    0.98,
                    f"{len(usable)} usable artifact(s) of the required type present.",
                    [str(a["artifact_id"]) for a in usable],
                    True,
                )
            return RuleResult(
                FAIL,
                0.95,
                f"{len(usable)} usable artifact(s) present; {minimum} required.",
                [str(a["artifact_id"]) for a in usable],
                True,
            )
        if pool:
            return RuleResult(
                UNVERIFIABLE,
                0.6,
                "An artifact of the required type is present but could not be parsed.",
                [str(a["artifact_id"]) for a in pool],
                True,
            )
        return RuleResult(FAIL, 0.99, "No artifact of the required type was submitted.", [], True)

    if kind == "DATE_WITHIN":
        field_name = params.get("field", "date")
        start = _parse_date(params.get("from") or params.get("start"))
        end = _parse_date(params.get("to") or params.get("end"))
        for artifact in pool:
            value = _parse_date(_field(artifact, field_name))
            if value is None:
                continue
            if (start and value < start) or (end and value > end):
                return RuleResult(
                    FAIL,
                    0.94,
                    f"{field_name} {value.isoformat()} falls outside "
                    f"{start.isoformat() if start else '-inf'}..{end.isoformat() if end else '+inf'}.",
                    [str(artifact["artifact_id"])],
                    True,
                )
            return RuleResult(
                PASS,
                0.93,
                f"{field_name} {value.isoformat()} is inside the required window.",
                [str(artifact["artifact_id"])],
                True,
            )
        return RuleResult(
            UNVERIFIABLE,
            0.55,
            f"No readable {field_name} was recovered from the evidence, so the "
            "date window cannot be checked in either direction.",
            [str(a["artifact_id"]) for a in pool],
            True,
        )

    if kind in {"AMOUNT_AT_LEAST", "QUANTITY_AT_LEAST"}:
        field_name = params.get("field", "total_paise" if kind == "AMOUNT_AT_LEAST" else "quantity")
        floor = _number(params.get("min") or params.get("minimum") or params.get("at_least"))
        best: tuple[float, dict[str, Any]] | None = None
        photo_only = True
        for artifact in pool:
            if str(artifact.get("artifact_type", "")).upper() != "PHOTO_SET":
                photo_only = False
            candidate = _number(_field(artifact, field_name))
            if candidate is None:
                continue
            if best is None or candidate > best[0]:
                best = (candidate, artifact)
        if best is None:
            if photo_only and pool:
                count = len(pool)
                return RuleResult(
                    UNVERIFIABLE,
                    0.5,
                    f"{count} photograph(s) cannot establish "
                    f"{'an amount' if kind == 'AMOUNT_AT_LEAST' else 'a count'} of "
                    f"{int(floor) if floor else 'the required quantity'}; nothing in the "
                    "pixels evidences a total, and nothing contradicts it either.",
                    [str(a["artifact_id"]) for a in pool],
                    True,
                )
            return RuleResult(
                UNVERIFIABLE,
                0.5,
                f"No readable {field_name} was recovered, so the floor cannot be checked.",
                [str(a["artifact_id"]) for a in pool],
                True,
            )
        measured, artifact = best
        if floor is None:
            return RuleResult(
                UNVERIFIABLE, 0.4, "The clause states no floor to compare against.", [], True
            )
        if measured >= floor:
            return RuleResult(
                PASS,
                0.95,
                f"{field_name} {measured:g} meets the floor of {floor:g}.",
                [str(artifact["artifact_id"])],
                True,
            )
        return RuleResult(
            FAIL,
            0.96,
            f"{field_name} {measured:g} is below the required {floor:g}.",
            [str(artifact["artifact_id"])],
            True,
        )

    if kind == "FIELD_EQUALS":
        field_name = params.get("field", "item_code")
        expected = params.get("value") or params.get("equals")
        found_any = False
        for artifact in pool:
            actual = _field(artifact, field_name)
            if actual in (None, "", []):
                continue
            found_any = True
            if str(actual).strip().upper() == str(expected).strip().upper():
                return RuleResult(
                    PASS,
                    0.96,
                    f"{field_name} is {actual}, matching {expected}.",
                    [str(artifact["artifact_id"])],
                    True,
                )
        if found_any:
            values = [
                str(_field(a, field_name))
                for a in pool
                if _field(a, field_name) not in (None, "", [])
            ]
            return RuleResult(
                FAIL,
                0.95,
                f"{field_name} is {', '.join(values)}; {expected} was required.",
                [str(a["artifact_id"]) for a in pool],
                True,
            )
        return RuleResult(
            UNVERIFIABLE,
            0.55,
            f"{field_name} was not recovered from any artifact, so it cannot be compared "
            f"with {expected}.",
            [str(a["artifact_id"]) for a in pool],
            True,
        )

    if kind == "FIELD_MATCHES_SPEC":
        field_name = params.get("field", "item_code")
        pattern = params.get("pattern") or params.get("spec")
        if not pattern:
            return RuleResult(UNVERIFIABLE, 0.4, "The clause states no pattern.", [], True)
        for artifact in pool:
            actual = _field(artifact, field_name)
            if actual in (None, "", []):
                continue
            if re.fullmatch(str(pattern), str(actual).strip(), flags=re.IGNORECASE):
                return RuleResult(
                    PASS,
                    0.93,
                    f"{field_name} {actual} matches the specification pattern.",
                    [str(artifact["artifact_id"])],
                    True,
                )
            return RuleResult(
                FAIL,
                0.93,
                f"{field_name} {actual} does not match the specification pattern.",
                [str(artifact["artifact_id"])],
                True,
            )
        return RuleResult(
            UNVERIFIABLE,
            0.5,
            f"{field_name} was not recovered, so it cannot be matched against the specification.",
            [str(a["artifact_id"]) for a in pool],
            True,
        )

    if kind == "VISUAL_CONSISTENT_WITH":
        expected_hex = params.get("colour") or params.get("color")
        tolerance = int(params.get("tolerance", 60))
        min_share = float(params.get("min_share", 0.08))
        legible = [a for a in pool if (a.get("fields") or {}).get("legible", False)]
        if not pool:
            return RuleResult(FAIL, 0.95, "No visual evidence was submitted.", [], False)
        if not legible:
            return RuleResult(
                UNVERIFIABLE,
                0.45,
                "The visual evidence is too degraded to compare with the approved specification.",
                [str(a["artifact_id"]) for a in pool],
                False,
            )
        if not expected_hex:
            return RuleResult(
                UNVERIFIABLE,
                0.45,
                "The clause names no approved colour to compare against.",
                [str(a["artifact_id"]) for a in legible],
                False,
            )
        target = _hex_to_rgb(str(expected_hex))
        if target is None:
            return RuleResult(
                UNVERIFIABLE, 0.4, "The approved colour is not a readable hex value.", [], False
            )

        # "Consistent with the specification" means the approved colour is present
        # in the frame in meaningful quantity -- not that it is the single most
        # frequent pixel, which for a studio photograph is the backdrop.
        #
        # The share is SUMMED across every palette bucket inside the tolerance.
        # Comparing one bucket at a time would make the verdict depend on where
        # the quantiser happened to split a continuous colour, which is an
        # artefact of the analyser rather than a fact about the goods.
        matched: list[str] = []
        missing: list[tuple[str, float, float]] = []
        for artifact in legible:
            fields = artifact.get("fields") or {}
            palette = [
                e
                for e in (fields.get("colour_palette") or [])
                if isinstance(e, dict) and _hex_to_rgb(str(e.get("hex", ""))) is not None
            ]
            if not palette:
                summary = fields.get("colour_summary")
                rgb = _hex_to_rgb(str(summary)) if summary else None
                if rgb is None:
                    return RuleResult(
                        UNVERIFIABLE,
                        0.45,
                        "No comparable colour information was produced from the visual evidence.",
                        [str(a["artifact_id"]) for a in legible],
                        False,
                    )
                distance = max(abs(a - b) for a, b in zip(rgb, target, strict=True))
                if distance <= tolerance:
                    matched.append(str(artifact["artifact_id"]))
                else:
                    missing.append((str(artifact["artifact_id"]), distance, 1.0))
                continue

            in_tolerance = 0.0
            closest = 255.0
            for entry in palette:
                rgb = _hex_to_rgb(str(entry["hex"]))
                assert rgb is not None
                distance = max(abs(a - b) for a, b in zip(rgb, target, strict=True))
                closest = min(closest, float(distance))
                if distance <= tolerance:
                    in_tolerance += float(entry.get("share") or 0.0)
            if in_tolerance >= min_share:
                matched.append(str(artifact["artifact_id"]))
            else:
                missing.append((str(artifact["artifact_id"]), closest, in_tolerance))

        if missing:
            worst = max(missing, key=lambda m: m[1])
            return RuleResult(
                FAIL,
                0.7,
                f"{len(missing)} photograph(s) do not show the approved colour across at "
                f"least {min_share:.0%} of the frame (worst: closest deviation "
                f"{worst[1]:.0f}, matching area {worst[2]:.1%}).",
                [m[0] for m in missing],
                False,
            )
        return RuleResult(
            PASS,
            0.72,
            f"Every photograph shows the approved colour within {tolerance} across at "
            f"least {min_share:.0%} of the frame.",
            matched,
            False,
        )

    return RuleResult(
        UNVERIFIABLE,
        0.3,
        f"Clause kind {kind} has no rubric, so it cannot be judged mechanically.",
        [],
        False,
    )
