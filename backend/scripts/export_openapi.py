"""``make docs`` -- write the OpenAPI document to ``docs/openapi.json``.

`docs/API.md` describes the envelope, the auth model and the error codes by
hand, because those are decisions rather than signatures.  The endpoint list is
generated, because a hand-maintained endpoint list is a list that goes stale.

    python -m scripts.export_openapi
"""

from __future__ import annotations

import json
from pathlib import Path

OUT = Path(__file__).resolve().parents[2] / "docs" / "openapi.json"


def main() -> int:
    # Imported here rather than at module scope: importing the app pulls in the
    # settings, and this script should fail with a clear message if the
    # environment is not loadable rather than at import time.
    from app.main import app

    document = app.openapi()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    paths = document.get("paths", {})
    operations = sum(
        1 for methods in paths.values() for method in methods if method.lower() != "parameters"
    )
    print(f"wrote {OUT.relative_to(OUT.parents[1])}: {len(paths)} paths, {operations} operations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
