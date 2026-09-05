"""I2 -- the import boundary, enforced.

**The LLM never moves money.**  Mechanically: nothing under ``app/agents/`` may
import ``app.settlement.engine``, ``app.rails`` or ``app.payments``, and nothing
under those money-moving packages may import ``app.agents``.

The check is an AST walk, not a grep, so it sees ``from x import y``,
``import x.y``, aliased imports and function-local imports alike.  It also
resolves **relative** imports to their absolute names -- ``from ...settlement.engine
import authorize_release`` inside ``app/agents/verifier/`` is exactly the thing
this lint exists to refuse -- and it treats ``importlib.import_module`` and
``__import__`` as imports, including refusing a module name that is built at
runtime and therefore cannot be checked at all.

    python -m scripts.import_lint          # exit 1 on violation
    python -m scripts.import_lint --json

CI runs this, and ``tests/security/test_import_boundary.py`` deliberately plants
a violation in a temporary tree and asserts that this script rejects it -- so the
guard itself is proven to work rather than merely present.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"

# The agent packages may not reach anything that can move money.
#
# `app.settlement.guards` is deliberately NOT forbidden: it is pure arithmetic
# with no I/O, no ORM and no rail, and it is the single definition of I3 and I4.
# Both halves of the system reading the same guard is the point -- the verifier
# must not be able to *call* the engine, but it must apply the same rule.
FORBIDDEN_FROM_AGENTS: tuple[str, ...] = (
    "app.settlement.engine",
    "app.rails",
    "app.payments",
    "app.deals.service",
    "app.deals.disputes",
    "app.deals.verification",
)

# And the money path may not reach the agents.
FORBIDDEN_FROM_MONEY: tuple[str, ...] = ("app.agents",)
MONEY_PACKAGES: tuple[str, ...] = ("app/settlement", "app/rails", "app/payments")

AGENT_PACKAGES: tuple[str, ...] = ("app/agents",)


@dataclass(slots=True)
class Violation:
    file: str
    line: int
    imported: str
    rule: str

    def render(self) -> str:
        return f"{self.file}:{self.line}  imports {self.imported}  [{self.rule}]"


def _package_of(relative: str) -> str:
    """``app/agents/verifier/pipeline.py`` -> ``app.agents.verifier``."""
    return ".".join(relative.split("/")[:-1])


def _absolutise(package: str, level: int, module: str) -> str:
    """Resolve a relative import to its absolute dotted name.

    ``from ...settlement.engine import authorize_release`` inside
    ``app/agents/verifier/pipeline.py`` is ``app.settlement.engine``.  The scanner
    used to skip every relative import on the grounds that one "cannot cross a
    package boundary here", which is simply not true: three dots from
    ``app.agents.verifier`` lands on ``app``, and everything under it is in reach.
    That was a hole straight through I2 -- the one invariant whose entire value is
    that it cannot be talked around.
    """
    parts = package.split(".") if package else []
    if level > len(parts):
        return module or ""
    base = parts[: len(parts) - (level - 1)]
    tail = module.split(".") if module else []
    return ".".join([*base, *tail])


# ``importlib.import_module("app.rails.base")`` is an import that the AST's
# ``Import`` nodes never see, and a lint that can be stepped around with one
# stdlib call is decoration.  Anything that resolves a module from a string is
# read as an import of whichever constant it is handed.  A *computed* name gets
# this marker, which matches every rule: a module name the lint cannot read is
# not a module name the lint can clear, and I2's whole value is that the boundary
# is decidable by looking.
_COMPUTED = "<computed module name>"

_DYNAMIC_IMPORT_CALLS: frozenset[str] = frozenset(
    {"import_module", "__import__", "find_spec", "module_from_spec", "spec_from_file_location"}
)


def _called_name(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _imported_modules(tree: ast.AST, package: str) -> list[tuple[int, str]]:
    """Every module this file pulls in: static, relative and dynamic alike."""
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.append((node.lineno, alias.name))
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                base = _absolutise(package, node.level, base)
            if base:
                found.append((node.lineno, base))
            for alias in node.names:
                found.append((node.lineno, f"{base}.{alias.name}" if base else alias.name))
        elif isinstance(node, ast.Call) and _called_name(node) in _DYNAMIC_IMPORT_CALLS:
            for argument in [*node.args, *(kw.value for kw in node.keywords)]:
                if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                    found.append((node.lineno, argument.value))
                elif not isinstance(argument, ast.Constant):
                    found.append((node.lineno, _COMPUTED))
    return found


def _matches(imported: str, forbidden: str) -> bool:
    if imported == _COMPUTED:
        return True
    return imported == forbidden or imported.startswith(forbidden + ".")


def scan(root: Path = APP) -> list[Violation]:
    violations: list[Violation] = []
    for path in sorted(root.rglob("*.py")):
        relative = path.relative_to(root.parent).as_posix()
        in_agents = any(relative.startswith(p + "/") for p in AGENT_PACKAGES)
        in_money = any(relative.startswith(p + "/") for p in MONEY_PACKAGES)
        if not (in_agents or in_money):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as exc:  # a file that will not parse is itself a failure
            violations.append(
                Violation(relative, exc.lineno or 0, f"<syntax error: {exc.msg}>", "PARSE")
            )
            continue
        rules = FORBIDDEN_FROM_AGENTS if in_agents else FORBIDDEN_FROM_MONEY
        rule_name = "I2/agents-may-not-move-money" if in_agents else "I2/money-may-not-call-agents"
        for line, imported in _imported_modules(tree, _package_of(relative)):
            for forbidden in rules:
                if _matches(imported, forbidden):
                    violations.append(Violation(relative, line, imported, rule_name))
                    break
    return violations


def main() -> int:
    parser = argparse.ArgumentParser(description="Enforce the I2 import boundary")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--root", default=str(APP))
    args = parser.parse_args()

    violations = scan(Path(args.root))
    if args.json:
        print(
            json.dumps(
                {
                    "ok": not violations,
                    "checked_packages": list(AGENT_PACKAGES + MONEY_PACKAGES),
                    "forbidden_from_agents": list(FORBIDDEN_FROM_AGENTS),
                    "forbidden_from_money": list(FORBIDDEN_FROM_MONEY),
                    "violations": [asdict(v) for v in violations],
                },
                indent=2,
            )
        )
        return 1 if violations else 0

    if violations:
        print("I2 IMPORT BOUNDARY VIOLATED -- the LLM must never be able to move money:\n")
        for v in violations:
            print(f"  {v.render()}")
        print(
            "\nThe verifier and the arbiter write attestations. A deterministic settlement "
            "engine reads them. If those two halves can import each other, that separation "
            "is a comment rather than a guarantee."
        )
        return 1

    print(
        f"I2 import boundary clean: nothing under {', '.join(AGENT_PACKAGES)} imports "
        f"{', '.join(FORBIDDEN_FROM_AGENTS)}, and nothing under "
        f"{', '.join(MONEY_PACKAGES)} imports {', '.join(FORBIDDEN_FROM_MONEY)}."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
