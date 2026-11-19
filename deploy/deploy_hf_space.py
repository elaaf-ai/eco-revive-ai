"""Deploy EcoRevive to a Hugging Face Docker Space and smoke-test it.

The token is read from the HF_TOKEN environment variable and is never written to disk.
The Gemini key is read from backend/.env and stored as a Space secret (runtime env var).

  $env:HF_TOKEN = "<token>"
  backend/.venv/Scripts/python deploy/deploy_hf_space.py --space <user>/ecorevive --private
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

import httpx
from huggingface_hub import HfApi

ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "backend" / "models" / "current"
WEB_EXCLUDES = shutil.ignore_patterns("node_modules", "dist", ".results", "e2e", "*.tsbuildinfo")


def read_env_file(path: Path) -> dict[str, str]:
    values = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip()
    return values


def verify_model() -> str:
    manifest = json.loads((MODEL_DIR / "manifest.json").read_text(encoding="utf-8"))
    digest = hashlib.sha256((MODEL_DIR / "model.onnx").read_bytes()).hexdigest()
    registry = json.loads((ROOT / "models" / "registry" / f"{manifest['version']}.json").read_text(encoding="utf-8"))
    if digest != registry["artifacts"]["onnx"]["sha256"]:
        sys.exit(f"model.onnx checksum {digest[:12]} does not match the registry. Re-run fetch_model.py.")
    return manifest["version"]


def stage(target: Path) -> None:
    shutil.copytree(ROOT / "web", target / "web", ignore=WEB_EXCLUDES)
    (target / "backend").mkdir()
    shutil.copytree(ROOT / "backend" / "app", target / "backend" / "app", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy2(ROOT / "backend" / "requirements.txt", target / "backend" / "requirements.txt")
    shutil.copytree(ROOT / "shared", target / "shared")
    (target / "models" / "current").mkdir(parents=True)
    for name in ("model.onnx", "manifest.json"):
        shutil.copy2(MODEL_DIR / name, target / "models" / "current" / name)
    shutil.copy2(ROOT / "deploy" / "hf-space" / "Dockerfile", target / "Dockerfile")
    shutil.copy2(ROOT / "deploy" / "hf-space" / "README.md", target / "README.md")


def wait_until_running(api: HfApi, space: str, timeout_s: int = 1800) -> str:
    started = time.time()
    last = ""
    while time.time() - started < timeout_s:
        stage_name = str(api.get_space_runtime(space).stage)
        if stage_name != last:
            print(f"  [{int(time.time() - started):4d}s] {stage_name}", flush=True)
            last = stage_name
        if stage_name.endswith("RUNNING"):
            return stage_name
        if "ERROR" in stage_name or stage_name.endswith("PAUSED"):
            return stage_name
        time.sleep(15)
    return f"TIMEOUT ({last})"


def smoke_test(url: str, token: str, image: Path) -> None:
    headers = {"Authorization": f"Bearer {token}"}
    with httpx.Client(base_url=url, headers=headers, timeout=60, follow_redirects=True) as client:
        for _ in range(20):
            ready = client.get("/readyz")
            if ready.status_code == 200:
                break
            time.sleep(10)
        print("readyz:", ready.status_code, ready.json() if ready.headers.get("content-type", "").startswith(
            "application/json") else ready.text[:200])
        home = client.get("/")
        print("home page:", home.status_code, "EcoRevive" in home.text)
        started = time.perf_counter()
        detect = client.post("/v1/detect", content=image.read_bytes(), headers={"Content-Type": "image/jpeg"})
        body = detect.json()
        print(f"detect: {detect.status_code} in {(time.perf_counter() - started) * 1000:.0f} ms,",
              [f"{d['class_name']} {d['confidence']:.2f}" for d in body.get("detections", [])][:6],
              "| model", body.get("model", {}).get("version"))
        guide = client.post("/v1/guides", json={"class_name": "Plastic", "confidence": 0.9})
        g = guide.json().get("guide", {})
        print("guide:", guide.status_code, g.get("source"), "|", g.get("source_detail"), "|", g.get("title"))
        hazard = client.post("/v1/guides", json={"class_name": "Hazardous", "confidence": 0.9}).json()["guide"]
        print("hazardous guide:", hazard["source"], hazard["kind"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--space", required=True, help="<username>/<space-name>")
    parser.add_argument("--private", action="store_true")
    parser.add_argument("--image", type=Path,
                        default=ROOT / "ml/data/processed/taco-5class-v1/images/val/batch_6_000017.jpg")
    parser.add_argument("--smoke-only", action="store_true")
    args = parser.parse_args()

    token = os.environ.get("HF_TOKEN")
    if not token:
        sys.exit("Set HF_TOKEN first.")
    api = HfApi(token=token)
    owner, name = args.space.split("/")
    url = f"https://{owner}-{name}.hf.space".lower().replace("_", "-").replace(".", "-")

    if not args.smoke_only:
        version = verify_model()
        print(f"model {version} verified")
        api.create_repo(args.space, repo_type="space", space_sdk="docker", private=args.private, exist_ok=True)
        gemini = read_env_file(ROOT / "backend" / ".env").get("GEMINI_API_KEY", "")
        if gemini:
            api.add_space_secret(args.space, "GEMINI_API_KEY", gemini)
            print("Gemini key stored as a Space secret")
        api.add_space_variable(args.space, "ECOREVIVE_MODEL_STATUS", "preview")
        api.add_space_variable(args.space, "ECOREVIVE_GEMINI_MODEL", "gemini-3.5-flash-lite")
        with tempfile.TemporaryDirectory() as tmp:
            stage(Path(tmp))
            api.upload_folder(folder_path=tmp, repo_id=args.space, repo_type="space",
                              commit_message=f"Deploy EcoRevive with model {version}")
        print("uploaded; building...")
        stage_name = wait_until_running(api, args.space)
        print("final stage:", stage_name)
        if not stage_name.endswith("RUNNING"):
            return 1

    print("URL:", url)
    smoke_test(url, token, args.image)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
