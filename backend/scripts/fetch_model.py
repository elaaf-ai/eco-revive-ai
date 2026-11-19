"""Install a model release from approved storage after verifying every checksum.

Reads models/registry/<version>.json (committed), downloads model.onnx from MODEL_BASE_URL
(or copies from --source-dir), checks SHA-256, and writes manifest.json beside it.
Exits non-zero and leaves nothing installed if any check fails.

  python scripts/fetch_model.py --version 0.1.0-preview \
      --source-dir ../ml/artifacts/0.1.0-preview --out models/current
  MODEL_BASE_URL=https://storage.example/ecorevive \
      python scripts/fetch_model.py --version 0.1.0-preview --out /app/models/current
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
import urllib.request
from pathlib import Path

REGISTRY = Path(__file__).resolve().parents[2] / "models" / "registry"
if not REGISTRY.is_dir():  # inside the container
    REGISTRY = Path("/app/models/registry")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--version", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--source-dir", type=Path, help="Local folder holding model.onnx instead of downloading")
    parser.add_argument("--base-url", default=os.environ.get("MODEL_BASE_URL", ""))
    args = parser.parse_args()

    entry_path = REGISTRY / f"{args.version}.json"
    if not entry_path.is_file():
        print(f"Unknown model version {args.version}: {entry_path} not found", file=sys.stderr)
        return 2
    entry = json.loads(entry_path.read_text(encoding="utf-8"))
    expected = entry["artifacts"]["onnx"]["sha256"]

    with tempfile.TemporaryDirectory() as tmp:
        staged = Path(tmp) / "model.onnx"
        if args.source_dir:
            shutil.copyfile(args.source_dir / "model.onnx", staged)
        elif args.base_url.startswith("https://"):
            url = f"{args.base_url.rstrip('/')}/{args.version}/model.onnx"
            with urllib.request.urlopen(url, timeout=120) as response, staged.open("wb") as out:
                shutil.copyfileobj(response, out)
        else:
            print("Provide --source-dir or an https:// MODEL_BASE_URL", file=sys.stderr)
            return 2

        actual = sha256(staged)
        if actual != expected:
            print(f"Checksum mismatch for model.onnx: expected {expected}, got {actual}", file=sys.stderr)
            return 3

        args.out.mkdir(parents=True, exist_ok=True)
        shutil.move(str(staged), args.out / "model.onnx")
        (args.out / "manifest.json").write_text(json.dumps(entry, indent=2) + "\n", encoding="utf-8")
    print(f"Installed model {args.version} into {args.out} (sha256 {expected[:12]}…)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
