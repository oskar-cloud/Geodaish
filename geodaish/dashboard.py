"""Actual training telemetry and replay export; no synthetic progress data."""

from collections import deque
import csv
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from uuid import uuid4

from geodaish.vision import make_env


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def record_replay(model, difficulty="normal", seed=10000, label="Senaste modellen", environment=None):
    env = make_env(difficulty=difficulty, **(environment or {}))
    state = env.unwrapped
    obs, _ = env.reset(seed=seed)
    frames = [[0.0, 0.0, 0, 0]]
    total = 0.0
    try:
        while True:
            action = int(model.predict(obs, deterministic=True)[0])
            obs, reward, terminated, truncated, info = env.step(action)
            total += reward
            frames.append([round(state.x, 5), round(state.y, 5), state.applied_action, state.passed])
            if terminated or truncated:
                break
        return {
            "id": f"{model.num_timesteps}-{seed}", "modelLabel": label,
            "modelStep": model.num_timesteps, "seed": seed,
            "fps": 60, "length": state.level_length, "speed": state.speed,
            "playerSize": state.player_size,
            "obstacles": [{"x": o.x, "count": o.count, "height": o.height} for o in state.obstacles],
            "frames": frames,
            "result": {"success": info["is_success"], "dead": info["dead"],
                       "progress": info["progress"], "reward": total, "jumps": info["jumps"]},
        }
    finally:
        env.close()


def validation_point(step, metrics, elapsed=None):
    return {"step": step, "elapsedSeconds": elapsed, "successRate": metrics["success_rate"],
            "meanProgress": metrics["mean_progress"], "meanReward": metrics["mean_reward"],
            "episodes": metrics["episodes"]}


class SnapshotPublisher:
    """Atomic local writes + a single background uploader with a latest-only queue."""

    def __init__(self, path, url=None, token=None, *, endpoint="/api/training"):
        self.path = Path(path)
        self.url = url
        self.token = token
        self.last_error = None
        self._pending = None
        self._closed = False
        self._condition = threading.Condition()
        self._thread = None
        if url:
            parsed = urlparse(url)
            if parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in ("localhost", "127.0.0.1")):
                raise ValueError("Dashboard URL must use HTTPS (HTTP is allowed only on localhost)")
            if parsed.username or parsed.password or parsed.query or parsed.fragment or not parsed.hostname:
                raise ValueError("Dashboard URL must not contain credentials, query strings, or fragments")
            if not token or len(token) < 32:
                raise ValueError("Set GEODAISH_DASHBOARD_TOKEN to the same 32+ character secret as TRAINING_API_TOKEN on Vercel")
            self.url = url.rstrip("/") + ("" if parsed.path.rstrip("/").endswith(endpoint) else endpoint)
            self._thread = threading.Thread(target=self._upload_loop, daemon=True)
            self._thread.start()

    def publish(self, snapshot):
        payload = json.dumps(snapshot, separators=(",", ":"), allow_nan=False).encode()
        if len(payload) > 512 * 1024:
            raise ValueError("Dashboard snapshot exceeds 512 KiB")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_name(f".{self.path.name}.{uuid4().hex}.tmp")
        temp.write_bytes(payload)
        os.replace(temp, self.path)
        if self._thread:
            with self._condition:
                self._pending = payload
                self._condition.notify()

    def _upload_loop(self):
        while True:
            with self._condition:
                self._condition.wait_for(lambda: self._pending is not None or self._closed)
                if self._pending is None:
                    return
                payload, self._pending = self._pending, None
            for attempt in range(3):
                try:
                    request = Request(self.url, data=payload, method="POST", headers={
                        "Content-Type": "application/json", "Authorization": f"Bearer {self.token}",
                    })
                    with urlopen(request, timeout=4) as response:
                        if response.status != 200:
                            raise URLError("Upload rejected")
                    self.last_error = None
                    break
                except (HTTPError, URLError, TimeoutError, OSError) as error:
                    status = getattr(error, "code", None)
                    message = f"HTTP {status}" if status else "network unavailable"
                    if self.last_error != message:
                        print(f"Dashboard upload: {message}. Local training and reports continue.", flush=True)
                    self.last_error = message
                    # A newer snapshot supersedes this one; don't build a stale backlog.
                    with self._condition:
                        newer = self._pending is not None
                    if newer or status in (400, 401, 403, 409, 413):
                        break
                    if attempt < 2:
                        time.sleep(0.5 * (attempt + 1))

    def close(self):
        if self._thread:
            with self._condition:
                self._closed = True
                self._condition.notify()
            self._thread.join(timeout=18)
            if self._thread.is_alive() or self.last_error:
                print("Dashboard: final remote update was not confirmed. The full report is saved locally.", flush=True)


class TrainingReporter:
    def __init__(self, args, output, initial_steps):
        self.started = time.perf_counter()
        self.initial_steps = initial_steps
        self.interval = args.report_every
        self.last_report = -float("inf")
        self.episodes = 0
        self.recent = deque(maxlen=100)
        self.publisher = SnapshotPublisher(args.dashboard_file,
            args.dashboard_url or os.environ.get("GEODAISH_DASHBOARD_URL"),
            os.environ.get("GEODAISH_DASHBOARD_TOKEN"))
        self.snapshot = {
            "schemaVersion": 1,
            "run": {"id": uuid4().hex, "label": output.name, "status": "running",
                    "algorithm": "PPO", "difficulty": args.difficulty, "seed": args.seed,
                    "numEnvs": args.envs, "initialSteps": initial_steps,
                    "targetSteps": initial_steps + args.steps, "startedAt": utc_now()},
            "telemetry": {"sequence": 0}, "history": [], "replay": None, "test": None,
        }
        if getattr(args, "environment", None):
            self.snapshot["run"]["environment"] = args.environment
        self.emit(initial_steps, force=True)

    def observe(self, infos, step):
        for info in infos:
            episode = info.get("episode")
            if episode:
                self.episodes += 1
                self.recent.append(episode)
        self.emit(step)

    def validation(self, model, metrics):
        elapsed = time.perf_counter() - self.started
        self.snapshot["history"].append(validation_point(model.num_timesteps, metrics, elapsed))
        self.snapshot["history"] = self.snapshot["history"][-1000:]
        self.snapshot["replay"] = record_replay(model, self.snapshot["run"]["difficulty"],
                                               environment=self.snapshot["run"].get("environment"))
        self.emit(model.num_timesteps, force=True)

    def emit(self, step, force=False):
        elapsed = time.perf_counter() - self.started
        if not force and elapsed - self.last_report < self.interval:
            return
        self.last_report = elapsed
        self.snapshot["telemetry"] = {
            "step": step, "elapsedSeconds": elapsed,
            "stepsPerSecond": (step - self.initial_steps) / max(elapsed, 0.001),
            "sequence": self.snapshot["telemetry"]["sequence"] + 1,
            "updatedAt": utc_now(), "episodes": self.episodes,
            "meanEpisodeReward": sum(float(e["r"]) for e in self.recent) / len(self.recent) if self.recent else None,
            "meanEpisodeLength": sum(int(e["l"]) for e in self.recent) / len(self.recent) if self.recent else None,
        }
        self.publisher.publish(self.snapshot)

    def finish(self, step, status):
        self.snapshot["run"]["status"] = status
        self.emit(step, force=True)
        self.publisher.close()


def export_dashboard(args):
    """Import original CSV metrics and a real model rollout, without inventing times."""
    from geodaish.cli import load_model
    folder = Path(args.run)
    config = json.loads((folder / "config.json").read_text())
    summary = json.loads((folder / "summary.json").read_text())
    with (folder / "progress.csv").open() as file:
        progress = list(csv.DictReader(file))
    final_step = int(progress[-1]["time/total_timesteps"])
    initial = final_step - summary["timesteps_this_run"]
    history = []
    with (folder / "validation.csv").open() as file:
        for row in csv.DictReader(file):
            metrics = {key: float(row[key]) for key in ("success_rate", "mean_progress", "mean_reward")}
            history.append(validation_point(int(row["timesteps"]), {**metrics, "episodes": 10}))
    history.append(validation_point(final_step, summary["validation"], summary["seconds"]))
    episodes, starts = [], []
    for path in (folder / "episodes").glob("*.monitor.csv"):
        with path.open() as file:
            header = json.loads(file.readline().lstrip("#"))
            starts.append(header["t_start"])
            episodes.extend(csv.DictReader(file))
    episodes.sort(key=lambda e: float(e["t"]))
    recent = episodes[-100:]
    start = min(starts) if starts else folder.stat().st_mtime
    stamp = lambda t: datetime.fromtimestamp(t, timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    model = load_model(args.model)
    snapshot = {
        "schemaVersion": 1,
        "run": {"id": f"import-{folder.name}", "label": folder.name, "status": "imported",
                "algorithm": "PPO", "difficulty": config["difficulty"], "seed": config["seed"],
                "numEnvs": config["envs"], "initialSteps": initial,
                "targetSteps": initial + config["steps"], "startedAt": stamp(start)},
        "telemetry": {"step": final_step, "elapsedSeconds": summary["seconds"],
                      "stepsPerSecond": summary["timesteps_this_run"] / summary["seconds"],
                      "sequence": 1, "updatedAt": stamp(start + summary["seconds"]),
                      "episodes": len(episodes),
                      "meanEpisodeReward": sum(float(e["r"]) for e in recent) / len(recent) if recent else None,
                      "meanEpisodeLength": sum(float(e["l"]) for e in recent) / len(recent) if recent else None},
        "history": history, "replay": record_replay(model, config["difficulty"], args.seed, "Sparad demomodell",
                                                     environment=config.get("environment")),
        "test": None,
    }
    if config.get("environment"):
        snapshot["run"]["environment"] = config["environment"]
    if args.evaluation:
        report = json.loads(Path(args.evaluation).read_text())
        snapshot["test"] = {"policies": [{"label": key, "episodes": value["episodes"],
            "successRate": value["success_rate"], "meanProgress": value["mean_progress"],
            "meanReward": value["mean_reward"], "firstSeed": value["first_seed"]}
            for key, value in report.items()]}
    SnapshotPublisher(args.output).publish(snapshot)
    print(f"Exported real training data and {len(snapshot['replay']['frames'])} replay frames to {args.output}")
