"""Deploy EcoRevive (plastic-only product) to Vercel and smoke-test the live site.

Stages a self-contained project (FastAPI entrypoint, built website, checksum-verified ONNX model,
pinned requirements), deploys it with the Vercel CLI so Vercel builds it on Linux, then checks
/readyz, a real scan and a Gemini guide.

The token is read from VERCEL_TOKEN and never written to disk. The Gemini key is read from
backend/.env and passed as a runtime environment variable of the deployment.

  $env:VERCEL_TOKEN = "<token>"
  backend/.venv/Scripts/python deploy/deploy_vercel.py
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from deploy_hf_space import read_env_file, verify_model  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "backend" / "models" / "current"
VERCEL_CLI = "vercel@66.2.0"

ENTRYPOINT = '''"""Vercel entrypoint: the EcoRevive FastAPI app with paths relative to this project."""
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, "backend"))
os.environ.setdefault("ECOREVIVE_MODEL_DIR", os.path.join(ROOT, "models", "current"))
os.environ.setdefault("ECOREVIVE_STATIC_DIR", os.path.join(ROOT, "web", "dist"))

from app.main import create_app  # noqa: E402

app = create_app()
'''


def build_web() -> None:
    npx = "npx.cmd" if os.name == "nt" else "npx"
    subprocess.run([npx, "vite", "build"], cwd=ROOT / "web", check=True)


def stage(target: Path) -> None:
    (target / "backend").mkdir(parents=True)
    shutil.copytree(ROOT / "backend" / "app", target / "backend" / "app", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(ROOT / "shared", target / "shared")
    shutil.copytree(ROOT / "web" / "dist", target / "web" / "dist")
    (target / "models" / "current").mkdir(parents=True)
    for name in ("model.onnx", "manifest.json"):
        shutil.copy2(MODEL_DIR / name, target / "models" / "current" / name)
    requirements = [
        line for line in (ROOT / "backend" / "requirements.txt").read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    ]
    (target / "requirements.txt").write_text("\n".join(requirements) + "\n", encoding="utf-8")
    (target / ".python-version").write_text("3.14\n", encoding="utf-8")
    (target / "index.py").write_text(ENTRYPOINT, encoding="utf-8")
    (target / "vercel.json").write_text(json.dumps({
        "$schema": "https://openapi.vercel.sh/vercel.json",
        "functions": {"index.py": {"maxDuration": 60}},
    }, indent=2) + "\n", encoding="utf-8")


def deploy(project_dir: Path, token: str, env: dict[str, str]) -> str:
    npx = "npx.cmd" if os.name == "nt" else "npx"
    command = [npx, "--yes", VERCEL_CLI, "deploy", "--prod", "--yes", "--token", token, "--cwd", str(project_dir)]
    for key, value in env.items():
        command += ["--env", f"{key}={value}"]
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
    log = (result.stdout + "\n" + result.stderr).replace(token, "***")
    for secret in env.values():
        if len(secret) > 20:
            log = log.replace(secret, "***")
    print(log[-4000:])
    if result.returncode != 0:
        sys.exit("Vercel deploy failed (see output above).")
    urls = re.findall(r"https://[a-z0-9.-]+\.vercel\.app", log)
    aliased = [u for u in urls if re.search(r"https://ecorevive(-[a-z0-9]+)?\.vercel\.app", u)]
    return (aliased or urls)[-1]


def smoke_test(url: str, image: Path) -> None:
    with httpx.Client(base_url=url, timeout=90, follow_redirects=True) as client:
        started = time.perf_counter()
        ready = client.get("/readyz")
        print(f"readyz: {ready.status_code} in {(time.perf_counter() - started) * 1000:.0f} ms (cold start included)")
        print("   ", ready.text[:300])
        home = client.get("/")
        print("home page:", home.status_code, "EcoRevive" in home.text)
        for attempt in (1, 2):
            started = time.perf_counter()
            detect = client.post("/v1/detect", content=image.read_bytes(), headers={"Content-Type": "image/jpeg"})
            body = detect.json()
            print(f"detect #{attempt}: {detect.status_code} in {(time.perf_counter() - started) * 1000:.0f} ms,",
                  [f"{d['class_name']} {d['confidence']:.2f}" for d in body.get("detections", [])],
                  "| enabled", body.get("model", {}).get("enabled_classes"))
        guide = client.post("/v1/guides", json={"class_name": "Plastic", "confidence": 1, "confirmed_by_user": True,
                                                "item_hint": "water bottle"})
        g = guide.json().get("guide", {})
        print("search guide:", guide.status_code, g.get("source"), "|", g.get("source_detail"), "|", g.get("title"))
        other = client.post("/v1/guides", json={"class_name": "Metal", "confidence": 0.9})
        print("non-plastic guide refused:", other.status_code, other.json().get("error", {}).get("code"))

        # Scan history (database) and the Gemini vision verdict, as the website's capture/upload sends them.
        browser = {"X-Client-Id": "deploy-smoke-test-0001"}
        print("history enabled:", ready.json().get("history_enabled"))
        saved = client.post("/v1/detect?save=true&verify=true", content=image.read_bytes(),
                            headers={"Content-Type": "image/jpeg", **browser}).json()
        print("saved scan:", saved.get("scan_id"), "| verdict:", (saved.get("verdict") or {}).get("message"))
        history = client.get("/v1/history", headers=browser)
        summary = history.json().get("you") if history.status_code == 200 else history.text
        print("history:", history.status_code, summary)
        cleared = client.delete("/v1/history", headers=browser)
        print("history cleared:", cleared.status_code, cleared.text[:80])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--image", type=Path,
                        default=ROOT / "ml/data/processed/taco-5class-v1/images/val/batch_6_000017.jpg")
    parser.add_argument("--smoke-only", metavar="URL")
    args = parser.parse_args()

    if args.smoke_only:
        smoke_test(args.smoke_only, args.image)
        return 0
    token = os.environ.get("VERCEL_TOKEN")
    if not token:
        sys.exit("Set VERCEL_TOKEN first.")
    print("model", verify_model(), "verified")
    build_web()
    env = {
        "ECOREVIVE_ENABLED_CLASSES": '["Plastic"]',
        "ECOREVIVE_MODEL_STATUS": "preview",
        "ECOREVIVE_ONNX_THREADS": "1",
        # Vercel overwrites X-Forwarded-For with the real client IP, so it is safe to trust here.
        "ECOREVIVE_CLIENT_IP_HEADER": "x-forwarded-for",
        "ECOREVIVE_GEMINI_MODEL": "gemini-3.5-flash-lite",
        "ECOREVIVE_LOG_LEVEL": "INFO",
    }
    gemini = read_env_file(ROOT / "backend" / ".env").get("GEMINI_API_KEY", "")
    if gemini:
        env["GEMINI_API_KEY"] = gemini
    # The Vercel CLI can keep the folder locked briefly on Windows, so cleanup errors are ignored.
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        project = Path(tmp) / "ecorevive"
        stage(project)
        url = deploy(project, token, env)
    print("URL:", url)
    smoke_test(url, args.image)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
