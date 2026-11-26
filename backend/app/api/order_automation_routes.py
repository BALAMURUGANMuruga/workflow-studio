# Expose FastAPI routes for planning tests, recording, saving scripts, and invoking the local Python runner.
"""Run bounded order tests against the bundled browser fixture."""

import json
from datetime import datetime, timezone
from hashlib import sha256
import os
from pathlib import Path
import re
import subprocess
import sys
from tempfile import NamedTemporaryFile, TemporaryDirectory
from threading import BoundedSemaphore, Lock
from time import monotonic, sleep
from urllib.parse import urlsplit
from uuid import uuid4
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, SecretStr

from ..auth.authentication_routes import get_current_user

router = APIRouter(prefix="/api/order-automation", dependencies=[Depends(get_current_user)])
run_slot = BoundedSemaphore(1)
recording_lock = Lock()
recordings = {}
DEFAULT_ORIGINS = "https://localhost:6443,https://127.0.0.1:6443,http://localhost:4200,http://127.0.0.1:4200"


class ScenarioBody(BaseModel):
    scenario: str = Field(min_length=1, max_length=10_000)


def _runner() -> tuple[Path, str]:
    location = os.getenv("ORDER_AUTOMATION_ROOT")
    root = Path(location).resolve() if location else Path(__file__).resolve().parents[3] / "order-automation"
    if not (root / "order_automation/workbench.py").is_file():
        raise HTTPException(503, "The Python order automation framework is unavailable on this server.")
    python = root / (".venv/Scripts/python.exe" if os.name == "nt" else ".venv/bin/python")
    return root, str(python if python.is_file() else sys.executable)


def _workbench(body: ScenarioBody, *, run: bool) -> dict:
    root, executable = _runner()
    try:
        reply = subprocess.run(
            [executable, "-m", "order_automation.workbench"], cwd=root,
            input=json.dumps({"scenario": body.scenario, "run": run}), capture_output=True,
            text=True, encoding="utf-8", errors="replace", timeout=95 if run else 10,
        )
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(504, "The automation runner timed out.") from exc
    except OSError as exc:
        raise HTTPException(503, "The Python automation runner could not start.") from exc
    if reply.returncode:
        raise HTTPException(503, "The Python automation runner is unavailable.")
    try:
        result = json.loads(reply.stdout)
    except ValueError as exc:
        raise HTTPException(502, "The automation runner returned an invalid response.") from exc
    if "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.post("/preview")
def preview_order_scenarios(body: ScenarioBody):
    return _workbench(body, run=False)


@router.post("/run")
def run_order_scenarios(body: ScenarioBody):
    if not run_slot.acquire(blocking=False):
        raise HTTPException(429, "Another order test is running. Try again when it finishes.")
    try:
        return _workbench(body, run=True)
    finally:
        run_slot.release()


class RecordingBody(BaseModel):
    url: str = Field(min_length=1, max_length=2000)


def _origins():
    return {value.strip().rstrip("/").lower() for value in
            os.getenv("ORDER_RECORDING_ORIGINS", DEFAULT_ORIGINS).split(",") if value.strip()}


def _validate_url(value: str, origins: set[str]):
    try:
        url = urlsplit(value)
        origin = f"{url.scheme}://{url.netloc}".lower()
    except ValueError as exc:
        raise HTTPException(400, "Enter a valid recording URL.") from exc
    if url.scheme not in ("http", "https") or url.username is not None or origin not in origins:
        raise HTTPException(400, "This URL is outside the configured recording origins.")


@router.post("/recordings")
def start_recording(body: RecordingBody, user=Depends(get_current_user)):
    origins = _origins()
    _validate_url(body.url, origins)
    root, python = _runner()
    owner = user.get("sub")
    with recording_lock:
        for key, (process, folder, _) in list(recordings.items()):
            if process.poll() is not None and monotonic() - folder[1] > 1200:
                folder[0].cleanup()
                del recordings[key]
        if any(process.poll() is None for process, _, _ in recordings.values()):
            raise HTTPException(409, "Stop the current browser recording before starting another.")
        storage = TemporaryDirectory(prefix="order-recorder-")
        path = Path(storage.name)
        try:
            (path / "config.json").write_text(json.dumps({"url": body.url, "origins": sorted(origins)}), encoding="utf-8")
            process = subprocess.Popen([python, "-m", "order_automation.recorder", str(path)],
                                       cwd=root, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as exc:
            storage.cleanup()
            raise HTTPException(503, "Could not launch the local Playwright recorder.") from exc
        key = uuid4().hex
        recordings[key] = (process, (storage, monotonic()), owner)
    deadline = monotonic() + 22
    while monotonic() < deadline and process.poll() is None and not (path / "ready").exists():
        sleep(.15)
    if (path / "ready").exists():
        return {"id": key}
    if process.poll() is None:
        process.kill()
    process.wait()
    with recording_lock:
        recordings.pop(key, None)
    detail = path / "error.txt"
    # Keep startup errors concise and exclude browser command lines.
    message = detail.read_text(encoding="utf-8") if detail.exists() else "Could not open the browser. Check Playwright and the configured target URL."
    storage.cleanup()
    raise HTTPException(503, message)


@router.post("/recordings/{recording_id}/stop")
def stop_recording(recording_id: str, user=Depends(get_current_user)):
    with recording_lock:
        item = recordings.get(recording_id)
        if item is None or item[2] != user.get("sub"):
            raise HTTPException(404, "Recording not found.")
        process, (storage, _), _ = recordings.pop(recording_id)
    path = Path(storage.name)
    try:
        (path / "stop").touch()
        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired as exc:
            process.kill()
            process.wait()
            raise HTTPException(503, "The recorder did not finish cleanly.") from exc
        result = path / "steps.json"
        if not result.is_file():
            raise HTTPException(503, "No recorded steps could be recovered.")
        return {"steps": json.loads(result.read_text(encoding="utf-8"))}
    finally:
        storage.cleanup()


class RecordedSecret(BaseModel):
    environment: Literal["ORDER_TEST_PASSWORD"]


class RecordedStep(BaseModel):
    action: Literal["navigate", "click", "fill", "select", "assertText", "assertTextExact", "assertVisible", "screenshot"]
    selector: str = Field(default="", max_length=1500)
    value: str = Field(default="", max_length=10_000)
    expected: str = Field(default="", max_length=10_000)
    url: str = Field(default="", max_length=2000)
    metadata: RecordedSecret | None = None


class RecordedScript(BaseModel):
    id: str | None = None
    name: str = Field(min_length=1, max_length=200)
    startUrl: str = Field(min_length=1, max_length=2000)
    description: str = Field(default="", max_length=2000)
    steps: list[RecordedStep] = Field(max_length=250)


def _script_directory(root: Path, user: dict) -> Path:
    return root / "recorded-tests" / sha256(str(user["sub"]).encode()).hexdigest()


def _read_script(directory: Path, script_id: str):
    if not re.fullmatch("[0-9a-f]{32}", script_id):
        raise HTTPException(404, "Recorded test not found.")
    try:
        return json.loads((directory / f"{script_id}.json").read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise HTTPException(404, "Recorded test not found.") from exc


@router.get("/scripts")
def list_recorded_scripts(user=Depends(get_current_user)):
    root, _ = _runner()
    directory = _script_directory(root, user)
    scripts = [_read_script(directory, path.stem) for path in directory.glob("*.json")]
    return sorted(scripts, key=lambda script: script["updatedOn"], reverse=True)


@router.get("/scripts/{script_id}")
def get_recorded_script(script_id: str, user=Depends(get_current_user)):
    root, _ = _runner()
    return _read_script(_script_directory(root, user), script_id)


@router.post("/scripts")
def save_recorded_script(body: RecordedScript, user=Depends(get_current_user)):
    root, _ = _runner()
    directory = _script_directory(root, user)
    origins = _origins()
    _validate_url(body.startUrl, origins)
    for step in body.steps:
        if step.action == "navigate":
            _validate_url(step.url or body.startUrl, origins)
        if step.metadata or (step.action == "fill" and "password" in step.selector.lower()):
            step.value = ""
            step.metadata = RecordedSecret(environment="ORDER_TEST_PASSWORD") if step.action == "fill" else None
    if body.id:
        _read_script(directory, body.id)
    script = body.model_dump(exclude_none=True)
    script.update(id=body.id or uuid4().hex, status="Draft",
                  updatedOn=datetime.now(timezone.utc).isoformat())
    directory.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(mode="w", encoding="utf-8", dir=directory, delete=False) as temporary:
        temporary_path = Path(temporary.name)
        try:
            json.dump(script, temporary)
        except Exception:
            temporary.close()
            temporary_path.unlink(missing_ok=True)
            raise
    try:
        temporary_path.replace(directory / f"{script['id']}.json")
    finally:
        temporary_path.unlink(missing_ok=True)
    return script


class RecordedRun(BaseModel):
    password: SecretStr | None = None


@router.post("/scripts/{script_id}/run")
def run_recorded_script(script_id: str, body: RecordedRun | None = None, user=Depends(get_current_user)):
    root, python = _runner()
    script = _read_script(_script_directory(root, user), script_id)
    origins = _origins()
    _validate_url(script["startUrl"], origins)
    if not script["steps"]:
        raise HTTPException(400, "Add at least one step before running this test.")
    password = body.password.get_secret_value() if body and body.password else None
    if password and len(password) > 1024:
        raise HTTPException(400, "The replay password exceeds 1024 characters.")
    if not run_slot.acquire(blocking=False):
        raise HTTPException(429, "Another order test is running. Try again when it finishes.")
    try:
        reply = subprocess.run([python, "-m", "order_automation.replay"], cwd=root,
                               input=json.dumps({"script": script, "origins": sorted(origins), "password": password}),
                               capture_output=True, encoding="utf-8", timeout=95)
        if reply.returncode:
            raise HTTPException(503, "Could not start the Playwright replay browser.")
        return json.loads(reply.stdout)
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(504, "The recorded test timed out.") from exc
    except (OSError, ValueError) as exc:
        raise HTTPException(503, "The Python replay runner is unavailable.") from exc
    finally:
        run_slot.release()
