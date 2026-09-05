"""I2 -- the import boundary, and proof that the guard itself works.

A lint that has never been seen to fail is not evidence of anything.  These
tests plant a violation in a temporary tree and assert the scanner rejects it.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from scripts.import_lint import (
    AGENT_PACKAGES,
    FORBIDDEN_FROM_AGENTS,
    FORBIDDEN_FROM_MONEY,
    MONEY_PACKAGES,
    scan,
)

BACKEND = Path(__file__).resolve().parents[2]
APP = BACKEND / "app"


def test_the_real_tree_is_clean():
    violations = scan(APP)
    assert violations == [], [v.render() for v in violations]


def test_the_cli_exits_zero_on_the_real_tree():
    result = subprocess.run(
        [sys.executable, "-m", "scripts.import_lint"], cwd=BACKEND, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stdout + result.stderr


def _tree(root: Path, files: dict[str, str]) -> Path:
    app = root / "app"
    for relative, source in files.items():
        path = app / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")
    return app


@pytest.mark.parametrize(
    "source",
    [
        "from app.settlement.engine import authorize_release",
        "import app.settlement.engine",
        "from app.rails.base import get_rail",
        "import app.rails",
        "from app.payments.webhooks import handle_webhook",
        "from app.settlement.engine import authorize_release as go",
    ],
)
def test_an_agent_importing_the_money_path_is_caught(tmp_path, source):
    app = _tree(tmp_path, {"agents/verifier/pipeline.py": source + "\n"})
    violations = scan(app)
    assert violations, f"{source!r} was not caught"
    assert all(v.rule == "I2/agents-may-not-move-money" for v in violations)


def test_a_function_local_import_is_also_caught(tmp_path):
    """A grep for imports at the top of the file would miss this."""
    app = _tree(
        tmp_path,
        {
            "agents/verifier/pipeline.py": (
                "def sneaky():\n"
                "    from app.settlement.engine import authorize_release\n"
                "    return authorize_release\n"
            )
        },
    )
    violations = scan(app)
    assert violations, "a function-local import must still be caught"
    assert violations[0].line == 2


@pytest.mark.parametrize(
    "source",
    [
        # `app/agents/verifier/` is three dots from `app`, so every one of these
        # resolves into the money path.  The scanner used to skip relative
        # imports outright, on the stated grounds that one "cannot cross a
        # package boundary here" -- which was simply false, and was a hole
        # straight through the one invariant whose value is that it cannot be
        # talked around.
        "from ...settlement.engine import authorize_release",
        "from ...settlement import engine",
        "from ...rails.base import get_rail",
        "from ...payments import webhooks",
        "from ...deals.service import fund_deal",
        "def sneaky():\n    from ...rails.base import get_rail\n    return get_rail\n",
    ],
)
def test_a_relative_import_into_the_money_path_is_caught(tmp_path, source):
    app = _tree(tmp_path, {"agents/verifier/pipeline.py": source + "\n"})
    violations = scan(app)
    assert violations, f"{source!r} was not caught"
    assert all(v.rule == "I2/agents-may-not-move-money" for v in violations)


@pytest.mark.parametrize(
    "source",
    [
        "import importlib\nm = importlib.import_module('app.settlement.engine')\n",
        "from importlib import import_module\nm = import_module('app.rails.base')\n",
        "m = __import__('app.payments.webhooks')\n",
        "import importlib.util\ns = importlib.util.find_spec('app.rails')\n",
        "def later():\n    import importlib\n    return importlib.import_module('app.rails')\n",
    ],
)
def test_a_dynamic_import_of_the_money_path_is_caught(tmp_path, source):
    """A boundary that one `importlib` call steps around is decoration."""
    app = _tree(tmp_path, {"agents/verifier/pipeline.py": source})
    violations = scan(app)
    assert violations, f"{source!r} was not caught"
    assert all(v.rule == "I2/agents-may-not-move-money" for v in violations)


def test_a_module_name_built_at_runtime_is_refused_outright(tmp_path):
    """The lint cannot read it, so the lint cannot clear it.

    I2's value is that the boundary is decidable by looking at the source.  A
    computed module name inside a checked package is therefore a violation on its
    own terms, whatever it happens to evaluate to.
    """
    app = _tree(
        tmp_path,
        {
            "agents/verifier/pipeline.py": (
                "import importlib\n"
                "name = 'app.' + 'settlement' + '.engine'\n"
                "m = importlib.import_module(name)\n"
            )
        },
    )
    violations = scan(app)
    assert violations
    assert "computed" in violations[0].imported
    assert violations[0].line == 3


def test_a_relative_import_inside_the_agents_package_stays_clean(tmp_path):
    """The agents may of course import each other."""
    app = _tree(
        tmp_path,
        {
            "agents/prompts.py": "CLAUSE_SYSTEM_PROMPT = ''\n",
            "agents/verifier/pipeline.py": (
                "from ..prompts import CLAUSE_SYSTEM_PROMPT\n"
                "from .schemas import ClauseEvaluation\n"
                "from ...settlement.guards import decide\n"
            ),
            "agents/verifier/schemas.py": "class ClauseEvaluation: pass\n",
        },
    )
    assert scan(app) == []


def test_a_dynamic_import_of_something_harmless_stays_clean(tmp_path):
    app = _tree(
        tmp_path,
        {"agents/verifier/pipeline.py": "import importlib\nm = importlib.import_module('json')\n"},
    )
    assert scan(app) == []


def test_the_money_path_importing_an_agent_is_caught(tmp_path):
    app = _tree(tmp_path, {"settlement/engine.py": "from app.agents._llm import get_provider\n"})
    violations = scan(app)
    assert violations
    assert violations[0].rule == "I2/money-may-not-call-agents"


@pytest.mark.parametrize(
    "source",
    [
        "from ..agents._llm import get_provider\n",
        "import importlib\nm = importlib.import_module('app.agents.verifier.pipeline')\n",
        "import importlib\nm = importlib.import_module('app.' + 'agents')\n",
    ],
)
def test_the_money_path_is_checked_in_the_same_directions(tmp_path, source):
    """Both halves of I2, and both bypasses, in both directions."""
    app = _tree(tmp_path, {"settlement/engine.py": source})
    violations = scan(app)
    assert violations, f"{source!r} was not caught"
    assert all(v.rule == "I2/money-may-not-call-agents" for v in violations)


def test_the_pure_guard_module_is_deliberately_allowed(tmp_path):
    """``app.settlement.guards`` is pure arithmetic with no I/O and no rail.

    Both halves of the system reading the same guard is the point: the verifier
    must not be able to *call* the engine, but it must apply the same rule.
    """
    app = _tree(
        tmp_path,
        {"agents/verifier/pipeline.py": "from app.settlement.guards import decide\n"},
    )
    assert scan(app) == []


def test_the_cli_exits_nonzero_and_says_why(tmp_path):
    app = _tree(tmp_path, {"agents/arbiter/pipeline.py": "from app.rails.base import get_rail\n"})
    result = subprocess.run(
        [sys.executable, "-m", "scripts.import_lint", "--root", str(app)],
        cwd=BACKEND,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "I2 IMPORT BOUNDARY VIOLATED" in result.stdout
    assert "agents/arbiter/pipeline.py" in result.stdout.replace("\\", "/")
    # The failure explains the invariant, so whoever hits it in CI understands
    # why the boundary exists rather than reaching for a suppression.
    assert "write attestations" in result.stdout
    assert "comment rather than a guarantee" in result.stdout


def test_the_json_output_is_machine_readable(tmp_path):
    import json

    app = _tree(tmp_path, {"agents/verifier/x.py": "import app.payments\n"})
    result = subprocess.run(
        [sys.executable, "-m", "scripts.import_lint", "--json", "--root", str(app)],
        cwd=BACKEND,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["violations"][0]["imported"] == "app.payments"
    assert set(payload["forbidden_from_agents"]) >= {
        "app.settlement.engine",
        "app.rails",
        "app.payments",
    }


def test_the_forbidden_lists_cover_the_invariant():
    """I2 names three packages explicitly; the lint must cover all three, in
    both directions."""
    assert {"app.settlement.engine", "app.rails", "app.payments"} <= set(FORBIDDEN_FROM_AGENTS)
    assert "app.agents" in FORBIDDEN_FROM_MONEY
    assert "app/agents" in AGENT_PACKAGES
    assert {"app/settlement", "app/rails", "app/payments"} <= set(MONEY_PACKAGES)


def test_the_verifier_cannot_reach_a_rail_at_runtime_either():
    """Not only the import graph: the verifier's own module namespace contains
    nothing that can move money."""
    import app.agents.verifier.pipeline as pipeline

    names = dir(pipeline)
    for forbidden in ("get_rail", "authorize_release", "execute_authorization", "Payout"):
        assert forbidden not in names, f"{forbidden} is reachable from the verifier"


def test_the_chain_adapter_accepts_only_hashes_and_integers():
    """I7 as a signature lint: no adapter method takes a free-text parameter."""
    import inspect

    from app.chain.adapter import ChainAdapter

    allowed = {
        "self",
        "deal_id_b32",
        "terms_hash",
        "buyer",
        "seller",
        "milestone_count",
        "dispute_window_ends",
        "seq",
        "evidence_root",
        "attestation_hash",
        "decision",
        "confidence_bps",
        "verifier_sig",
        "amount_paise",
        "rail_ref_hash",
        "human_approved",
        "release_paise",
        "refund_paise",
        "decision_hash",
        "tx_hash",
    }
    for name in (
        "open_deal",
        "anchor_attestation",
        "record_settlement",
        "resolve_dispute",
        "raise_dispute",
        "read_milestone",
    ):
        signature = inspect.signature(getattr(ChainAdapter, name))
        for parameter in signature.parameters:
            assert parameter in allowed, f"{name}({parameter}) is not a hash, id or integer"
