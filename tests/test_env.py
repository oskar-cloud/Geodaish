import numpy as np
import pytest
from gymnasium.utils.env_checker import check_env

from geodaish.env import DashEnv, SpikeGroup, heuristic_action


def test_gymnasium_contract():
    check_env(DashEnv(), skip_render_check=True)


def test_seed_replays_identical_trajectory():
    a, b = DashEnv(), DashEnv()
    np.testing.assert_array_equal(a.reset(seed=123)[0], b.reset(seed=123)[0])
    assert a.obstacles == b.obstacles
    for _ in range(1000):
        action = heuristic_action(a._observation())
        first, second = a.step(action), b.step(action)
        np.testing.assert_array_equal(first[0], second[0])
        assert first[1:] == second[1:]
        if first[2] or first[3]:
            break


def test_idle_hits_first_obstacle():
    env = DashEnv()
    env.reset(seed=7)
    for _ in range(1000):
        _, reward, terminated, truncated, info = env.step(0)
        if terminated or truncated:
            break
    assert terminated and not truncated and info["dead"]
    assert not info["is_success"] and info["obstacles_passed"] == 0
    assert reward < 0
    with pytest.raises(RuntimeError):
        env.step(0)


@pytest.mark.parametrize("difficulty", ["easy", "normal", "hard"])
def test_reference_can_finish_generated_levels(difficulty):
    env = DashEnv(difficulty=difficulty)
    for seed in range(20):
        obs, _ = env.reset(seed=seed)
        while True:
            obs, _, terminated, truncated, info = env.step(heuristic_action(obs))
            assert env.observation_space.contains(obs)
            if terminated or truncated:
                break
        assert info["is_success"], (difficulty, seed, info)
        assert info["obstacles_passed"] == env.group_count


def test_timeout_is_truncation_not_death():
    env = DashEnv(max_steps=1)
    env.reset(seed=1)
    _, _, terminated, truncated, info = env.step(0)
    assert truncated and not terminated and not info["dead"]


def test_cannot_double_jump():
    env = DashEnv()
    env.reset(seed=1)
    env.step(1)
    velocity = env.vy
    env.step(1)
    assert env.vy < velocity and env.jumps == 1


def test_collision_follows_triangle_not_bounding_box():
    env = DashEnv()
    env.reset(seed=1)
    obstacle = SpikeGroup(4.0, 1)
    env.x, env.y = 3.3, 0.3
    assert not env._collides(obstacle)
    env.x = 3.6
    assert env._collides(obstacle)
    env.y = 1.0
    assert not env._collides(obstacle)


def test_rgb_render_works_without_display():
    env = DashEnv(render_mode="rgb_array")
    env.reset(seed=1)
    frame = env.render()
    assert frame.shape == (620, 1100, 3)
    assert frame.dtype == np.uint8
    assert frame.std() > 0
    env.close()
