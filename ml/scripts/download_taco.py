"""Download TACO images listed in a pinned annotations file. Safe to re-run."""

from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlparse

import requests
from tqdm import tqdm

# The two image hosts referenced by the pinned TACO annotations file.
ALLOWED_HOSTS = {"img.tacodataset.org", "olm-s3.s3.eu-west-1.amazonaws.com"}


def fetch(session: requests.Session, url: str, target: Path) -> str | None:
    if target.exists() and target.stat().st_size > 0:
        return None
    if urlparse(url).hostname not in ALLOWED_HOSTS:
        return f"blocked host: {url}"
    try:
        response = session.get(url, timeout=60)
        response.raise_for_status()
    except requests.RequestException as exc:
        return f"{url}: {exc}"
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(".part")
    partial.write_bytes(response.content)
    partial.replace(target)
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--annotations", type=Path, default=Path("ml/data/raw/taco/annotations.json"))
    parser.add_argument("--out", type=Path, default=Path("ml/data/raw/taco/images"))
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()

    images = json.loads(args.annotations.read_text(encoding="utf-8"))["images"]
    failures: list[str] = []
    with requests.Session() as session, ThreadPoolExecutor(args.workers) as pool:
        jobs = [
            pool.submit(fetch, session, i.get("flickr_640_url") or i["flickr_url"], args.out / i["file_name"])
            for i in images
        ]
        for job in tqdm(as_completed(jobs), total=len(jobs), desc="TACO images"):
            if error := job.result():
                failures.append(error)

    print(f"images={len(images)} failed={len(failures)}")
    for failure in failures[:20]:
        print("FAILED", failure)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
