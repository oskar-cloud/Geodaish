import numpy as np
import pytest
from gymnasium.utils.env_checker import check_env

from geodaish.calibration import measure_jump
from geodaish.env import DashEnv, heuristic_action
from geodaish.vision import PerceptionError, PixelObserver, make_env


def test_pixel_contract_and_no_state_observation_leak():
    env = make_env(observations="pixels", level="test")
    try:
        check_env(env, skip_render_check=True)
        env.unwrapped._observation = lambda: np.full(16, np.nan, dtype=np.float32)
        obs, _ = env.reset(seed=1)
        assert env.observation_space.contains(obs)
        obs, *_ = env.step(0)
        assert env.observation_space.contains(obs)
        assert obs[3] * 10 == pytest.approx(7, abs=0.3)
        assert env.detection.cube.left == 190
        assert len(env.detection.spikes) == 1
    finally:
        env.close()


def test_pixels_follow_jump_height_and_velocity():
    env = make_env(observations="pixels", level="test")
    try:
        env.reset(seed=1)
        for frame in range(40):
            obs, *_ = env.step(int(frame == 0))
            assert obs[0] * 3 == pytest.approx(env.unwrapped.y, abs=0.03)
            assert obs[1] * 12 == pytest.approx(env.unwrapped.vy, abs=1.8)
            assert bool(obs[2]) == env.unwrapped.grounded
    finally:
        env.close()


@pytest.mark.parametrize("difficulty", ["easy", "normal", "hard"])
def test_pixel_reference_finishes_fixed_course(difficulty):
    env = make_env(observations="pixels", level="test", difficulty=difficulty)
    try:
        obs, _ = env.reset(seed=1)
        while True:
            obs, _, terminated, truncated, info = env.step(heuristic_action(obs))
            if terminated or truncated:
                break
        assert info["is_success"]
        assert info["obstacles_passed"] == 4
        assert not info["vision_valid"]
    finally:
        env.close()


def test_missing_cube_or_ground_never_reuses_stale_detection():
    env = make_env(observations="pixels", level="test")
    try:
        env.reset(seed=1)
        frame = env.frame.copy()
        cube = env.detection.cube
        frame[cube.top:cube.bottom, cube.left:cube.right] = 0
        with pytest.raises(PerceptionError, match="one cube"):
            env.observer.observe(frame, 1 / 60)
        with pytest.raises(PerceptionError, match="Ground"):
            PixelObserver().observe(np.zeros_like(frame), 0)
        with pytest.raises(PerceptionError, match="timestamps"):
            env.observer.observe(env.frame, 0)
    finally:
        env.close()


def test_detector_groups_adjacent_spikes_and_does_not_invent_unseen_hazards():
    from geodaish.env import SpikeGroup
    env = make_env(observations="pixels")
    try:
        env.reset(seed=1)
        env.unwrapped.obstacles = [SpikeGroup(4, 3), SpikeGroup(10, 2), SpikeGroup(20, 1)]
        env.observer.reset()
        obs = env._capture()
        assert len(env.detection.spikes) == 2
        # Three-pixel polygon outlines extend beyond the collision geometry.
        assert obs[5] * 3 == pytest.approx(2.1, abs=3 / 68)
        assert obs[9] * 3 == pytest.approx(1.4, abs=3 / 68)
        np.testing.assert_array_equal(obs[12:], np.zeros(4))
    finally:
        env.close()


def test_input_delay_applies_to_press_release_and_resets():
    env = DashEnv(input_delay=2, level="test")
    env.reset(seed=1)
    applied = [env.step(action)[4]["applied_action"] for action in (1, 0, 0, 0)]
    assert applied == [0, 0, 1, 0]
    assert env.jumps == 1
    env.step(1)
    env.reset(seed=2)
    assert [env.step(0)[4]["applied_action"] for _ in range(3)] == [0, 0, 0]
    assert env.jumps == 0


def test_pixel_time_limit_keeps_observation_for_value_bootstrap():
    env = make_env(observations="pixels", level="test", max_steps=1)
    try:
        env.reset(seed=0)
        obs, _, terminated, truncated, info = env.step(0)
        assert truncated and not terminated and info["vision_valid"]
        assert obs[2] == 1 and obs[7] == 1
    finally:
        env.close()


@pytest.mark.parametrize("delay", [0, 2, 6])
def test_calibration_measures_jump_and_distinguishes_tick_from_queue(delay):
    report = measure_jump(input_delay=delay)
    m = report["measurements"]
    physics = report["training"]["physics"]
    assert m["input_delay_frames"] == delay
    assert m["command_to_first_motion_ms"] == pytest.approx((delay + 1) * 1000 / 60)
    assert m["peak_height"] == pytest.approx(1.95, abs=0.03)
    assert m["airtime_seconds"] == pytest.approx(2 / 3, abs=1 / 60)
    assert physics["gravity"] == pytest.approx(36, abs=0.5)
    assert physics["jump_velocity"] == pytest.approx(12, abs=0.15)
    assert physics["speed"] == pytest.approx(7, abs=0.3)


@pytest.mark.parametrize("options", [
    {"input_delay": -1}, {"input_delay": 31}, {"input_delay": 0.5},
    {"level": "missing"}, {"physics": {"gravity": float("nan")}},
    {"physics": {"speed": -1}}, {"physics": {"unknown": 1}},
])
def test_invalid_simulation_profiles_are_rejected(options):
    with pytest.raises(ValueError):
        make_env(**options)
