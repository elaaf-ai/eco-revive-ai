"""Train a notebook baseline against an explicit data.yaml, or resume from last.pt."""

from __future__ import annotations

import argparse
import json
import platform
import sys
from pathlib import Path

import torch
import ultralytics
import yaml
from ultralytics import YOLO

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ecorevive_ml.labels import canonical_names


def mark_complete(run_dir: Path) -> None:
    """Record a finished run, because Ultralytics refuses to resume a completed last.pt."""
    (run_dir / "complete.json").write_text(json.dumps({"complete": True}) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True, help="Explicit path to data.yaml")
    parser.add_argument("--baseline", choices=["nano", "small"], default="nano")
    parser.add_argument("--config", type=Path, default=Path("ml/configs/baselines.yaml"))
    parser.add_argument("--project", type=Path, default=Path("ml/runs"))
    parser.add_argument("--name", default=None)
    parser.add_argument("--batch", type=int, default=None, help="Override batch size for smaller GPUs")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--resume", type=Path, default=None, help="Path to a compatible last.pt")
    args = parser.parse_args()

    if args.resume:
        YOLO(str(args.resume)).train(resume=True)
        mark_complete(args.resume.resolve().parents[1])
        return 0

    if not args.data.is_file():
        parser.error(f"Dataset file not found: {args.data}")
    data = yaml.safe_load(args.data.read_text(encoding="utf-8"))
    names = data["names"]
    names = [names[i] for i in sorted(names)] if isinstance(names, dict) else list(names)
    if names != canonical_names():
        parser.error(f"Dataset classes {names} differ from canonical {canonical_names()}")

    config = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    params = dict(config["baselines"][args.baseline])
    if args.batch:
        params["batch"] = args.batch
    model_name = params.pop("model")
    run_name = args.name or f"ecorevive_{args.baseline}"
    project = args.project.resolve()

    run_dir = project / run_name
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "environment.json").write_text(
        json.dumps(
            {
                "python": platform.python_version(),
                "torch": torch.__version__,
                "ultralytics": ultralytics.__version__,
                "device": torch.cuda.get_device_name(0) if torch.cuda.is_available() else "cpu",
                "seed": config["seed"],
                "data": str(args.data),
                "model": model_name,
                "params": params,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    YOLO(model_name).train(
        data=str(args.data.resolve()),
        project=str(project),
        name=run_name,
        exist_ok=True,
        seed=config["seed"],
        deterministic=True,
        workers=args.workers,
        save_period=5,
        device=0 if torch.cuda.is_available() else "cpu",
        **params,
    )
    mark_complete(run_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
