"""Bundle the processed dataset and pipeline code into one checksummed ZIP for Google Drive."""

from __future__ import annotations

import argparse
import hashlib
import zipfile
from pathlib import Path

CODE_PATHS = ["shared/classes.json", "ml/configs", "ml/ecorevive_ml", "ml/scripts"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=Path("ml/data/processed/taco-5class-v1"))
    parser.add_argument("--out", type=Path, default=Path("ml/artifacts/ecorevive-colab-bundle.zip"))
    args = parser.parse_args()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(args.out, "w", zipfile.ZIP_STORED) as bundle:
        for path in sorted(args.dataset.rglob("*")):
            if path.is_file() and path.suffix != ".cache":
                bundle.write(path, Path("dataset") / path.relative_to(args.dataset))
        for root in CODE_PATHS:
            source = Path(root)
            files = [source] if source.is_file() else sorted(source.rglob("*"))
            for path in files:
                if path.is_file() and "__pycache__" not in path.parts:
                    bundle.write(path, Path("code") / path)

    digest = hashlib.sha256(args.out.read_bytes()).hexdigest()
    print(f"bundle={args.out}\nbytes={args.out.stat().st_size}\nsha256={digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
