import importlib.util
import json
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "ci_gate", Path(__file__).resolve().parents[2] / ".github" / "scripts" / "ci_gate.py"
)
ci_gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ci_gate)

JOBS = ("ml", "backend", "web", "e2e", "mobile", "docker")


def run(name, conclusion, started="2026-11-20T10:00:00Z"):
    return {"name": name, "conclusion": conclusion, "status": "completed", "started_at": started}


def test_passes_only_when_every_named_job_succeeded():
    ok, _ = ci_gate.evaluate([{"check_runs": [run(n, "success") for n in JOBS]}])
    assert ok


def test_release_job_alone_does_not_pass():
    ok, states = ci_gate.evaluate([{"check_runs": [{"name": "gate", "conclusion": None, "status": "in_progress"}]}])
    assert not ok and states["backend"] == "missing"


def test_failure_and_pagination_and_latest_rerun():
    page1 = {"check_runs": [run(n, "success") for n in JOBS[:3]]}
    page2 = {"check_runs": [run("e2e", "failure"), run("e2e", "success", "2026-11-20T11:00:00Z"),
                            run("mobile", "success"), run("docker", "failure")]}
    raw = json.dumps(page1) + "\n" + json.dumps(page2)
    ok, states = ci_gate.evaluate(ci_gate.parse_pages(raw))
    assert not ok and states["e2e"] == "success" and states["docker"] == "failure"
