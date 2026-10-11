import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.error import HTTPError

import pytest

from geodaish.cli import load_model
from geodaish.dashboard import SnapshotPublisher, TrainingReporter, record_replay
from geodaish.env import DashEnv


def test_recorded_replay_matches_actual_physics_for_every_action():
    model = load_model(Path(__file__).resolve().parents[1] / "models/demo-normal.zip")
    replay = record_replay(model, seed=20000)
    env = DashEnv()
    env.reset(seed=20000)
    for frame in replay["frames"][1:]:
        _, _, terminated, truncated, _ = env.step(frame[2])
        assert frame[:2] == [round(env.x, 5), round(env.y, 5)]
        assert frame[3] == env.passed
    assert terminated or truncated
    assert replay["result"]["success"] == env.success
    env.close()


def test_atomic_local_snapshot_and_finite_json(tmp_path):
    file = tmp_path / "nested/live.json"
    publisher = SnapshotPublisher(file)
    publisher.publish({"step": 1})
    publisher.publish({"step": 2})
    assert json.loads(file.read_text()) == {"step": 2}
    assert not list(file.parent.glob("*.tmp"))
    with pytest.raises(ValueError):
        publisher.publish({"bad": float("nan")})
    assert json.loads(file.read_text()) == {"step": 2}


def test_uploader_uses_auth_and_sends_final_update(tmp_path):
    requests = []
    class Response:
        status = 200
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
    def receive(request, timeout):
        requests.append(request)
        return Response()
    with patch("geodaish.dashboard.urlopen", receive):
        publisher = SnapshotPublisher(tmp_path / "live.json", "https://example.vercel.app", "x" * 32)
        publisher.publish({"step": 1})
        publisher.publish({"step": 2, "status": "completed"})
        publisher.close()
    assert json.loads(requests[-1].data)["status"] == "completed"
    assert requests[-1].full_url == "https://example.vercel.app/api/training"
    assert requests[-1].get_header("Authorization") == "Bearer " + "x" * 32


def test_network_rejection_preserves_local_training_report(tmp_path):
    file = tmp_path / "live.json"
    with patch("geodaish.dashboard.urlopen", side_effect=HTTPError("https://example.vercel.app", 401, "Rejected", {}, None)):
        publisher = SnapshotPublisher(file, "https://example.vercel.app", "x" * 32)
        publisher.publish({"status": "completed"})
        publisher.close()
    assert json.loads(file.read_text())["status"] == "completed"
    assert publisher.last_error == "HTTP 401"


@pytest.mark.parametrize("url", ["http://example.com", "https://secret@example.com", "https://example.com?token=secret"])
def test_publisher_rejects_unsafe_remote_urls(tmp_path, url):
    with pytest.raises(ValueError):
        SnapshotPublisher(tmp_path / "live.json", url, "x" * 32)


def test_resumed_training_reports_run_progress_and_termination(tmp_path, monkeypatch):
    monkeypatch.delenv("GEODAISH_DASHBOARD_URL", raising=False)
    args = SimpleNamespace(report_every=5, dashboard_file=tmp_path / "live.json", dashboard_url=None,
                           difficulty="normal", seed=43, envs=4, steps=1000)
    reporter = TrainingReporter(args, tmp_path, initial_steps=120000)
    reporter.observe([{"episode": {"r": 10.0, "l": 80}}], 120100)
    reporter.finish(121024, "interrupted")
    report = json.loads(args.dashboard_file.read_text())
    assert report["run"]["targetSteps"] == 121000
    assert report["run"]["status"] == "interrupted"
    assert report["telemetry"]["step"] == 121024
    assert report["telemetry"]["episodes"] == 1
    assert report["telemetry"]["meanEpisodeReward"] == 10
    assert report["telemetry"]["sequence"] >= 2
