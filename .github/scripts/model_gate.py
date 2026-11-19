"""Release gate: production requires a model whose locked-test evaluation met the target.

Usage: python .github/scripts/model_gate.py <version> <preview|production>
"""

import json
import sys
from pathlib import Path

TARGET = 0.85


def main() -> int:
    version, channel = sys.argv[1], sys.argv[2]
    entry_path = Path(__file__).resolve().parents[2] / "models" / "registry" / f"{version}.json"
    if not entry_path.is_file():
        print(f"No registry entry for {version}")
        return 1
    evaluation = json.loads(entry_path.read_text(encoding="utf-8"))["evaluation"]
    if channel == "preview":
        print(f"{version}: preview release allowed (evaluation status: {evaluation['status']})")
        return 0
    map50 = evaluation.get("locked_test_map50")
    if channel == "production" and evaluation.get("meets_target") and map50 is not None and map50 >= TARGET:
        print(f"{version}: production allowed, locked test mAP@0.50 = {map50}")
        return 0
    print(f"{version}: blocked for production. Locked test mAP@0.50 = {map50}, target {TARGET}.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
