"""Deterministic fixed-step cube physics; rendering never drives simulation."""

from dataclasses import dataclass
from collections import deque
import math

import gymnasium as gym
import numpy as np
from gymnasium import spaces


@dataclass(frozen=True)
class SpikeGroup:
    x: float
    count: int
    height: float = 0.9

    @property
    def width(self) -> float:
        return self.count * 0.7


DIFFICULTIES = {
    "easy": (6.0, 1, 8),
    "normal": (7.0, 2, 12),
    "hard": (8.0, 3, 16),
}


class DashEnv(gym.Env):
    """Actions: 0 = release, 1 = hold jump (repeats on landing).

    Observation: height, vertical speed, grounded, speed, followed by three
    groups of [distance from player front, width, height, present]. Values are
    normalized into [-1, 1]. No level seed or absolute progress is observed.
    """

    metadata = {"render_modes": ["human", "rgb_array"], "render_fps": 60}
    player_size = 0.8
    gravity = 36.0
    jump_velocity = 12.0
    dt = 1.0 / 60.0
    lookahead = 16.0

    def __init__(self, render_mode=None, difficulty="normal", max_steps=1800,
                 level="generated", input_delay=0, physics=None):
        if difficulty not in DIFFICULTIES:
            raise ValueError(f"Unknown difficulty: {difficulty}")
        if render_mode not in (None, *self.metadata["render_modes"]):
            raise ValueError(f"Unsupported render mode: {render_mode}")
        if max_steps < 1:
            raise ValueError("max_steps must be positive")
        if level not in ("generated", "test"):
            raise ValueError("level must be generated or test")
        if isinstance(input_delay, bool) or not isinstance(input_delay, int) or not 0 <= input_delay <= 30:
            raise ValueError("input_delay must be an integer from 0 to 30 frames")
        self.level = level
        self.input_delay = input_delay
        self.render_mode = render_mode
        self.difficulty = difficulty
        self.max_steps = max_steps
        self.speed, self.max_spikes, self.group_count = DIFFICULTIES[difficulty]
        if physics is not None and not isinstance(physics, dict):
            raise ValueError("physics must be an object with speed, gravity and/or jump_velocity")
        for key, value in (physics or {}).items():
            if key not in ("speed", "gravity", "jump_velocity"):
                raise ValueError(f"Unknown physics setting: {key}")
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ValueError(f"{key} must be positive and finite")
            setattr(self, key, float(value))
        self.action_space = spaces.Discrete(2)
        self.observation_space = spaces.Box(-1, 1, shape=(16,), dtype=np.float32)
        self._renderer = None
        self._done = True
        self.closed = False
        self._inputs = deque([0] * self.input_delay)
        self.applied_action = 0

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        self.x = self.y = self.vy = 0.0
        self.steps = self.passed = self.jumps = 0
        self._done = self.dead = self.success = False
        self.closed = False
        self._inputs = deque([0] * self.input_delay)
        self.applied_action = 0
        cursor = float(self.np_random.uniform(8.0, 11.0))
        self.obstacles = []
        for _ in range(self.group_count):
            count = int(self.np_random.integers(1, self.max_spikes + 1))
            obstacle = SpikeGroup(cursor, count)
            self.obstacles.append(obstacle)
            # Leave enough room to land and jump again at every difficulty.
            cursor += obstacle.width + float(self.np_random.uniform(5.0, 8.0))
        if self.level == "test":
            # A fixed, inspectable course: flat ground, one spike at a time.
            self.obstacles = [SpikeGroup(x, 1) for x in (8.0, 16.0, 24.0, 32.0)]
        self.group_count = len(self.obstacles)
        self.level_length = self.obstacles[-1].x + self.obstacles[-1].width + 6.0
        if self.render_mode == "human":
            self.render()
        return self._observation(), self._info()

    @property
    def grounded(self):
        return self.y <= 0.0

    def _observation(self):
        obs = np.zeros(16, dtype=np.float32)
        obs[:4] = (self.y / 3.0, self.vy / 12.0, float(self.grounded), self.speed / 10)
        upcoming = [o for o in self.obstacles if o.x + o.width > self.x]
        for i, obstacle in enumerate(upcoming[:3]):
            distance = obstacle.x - (self.x + self.player_size)
            if distance <= self.lookahead:
                obs[4 + 4 * i:8 + 4 * i] = (
                    distance / self.lookahead, obstacle.width / 3,
                    obstacle.height / 2, 1,
                )
        return np.clip(obs, -1, 1)

    def _info(self):
        return {
            "progress": min(self.x / self.level_length, 1.0),
            "obstacles_passed": self.passed,
            "is_success": self.success,
            "dead": self.dead,
            "jumps": self.jumps,
            "applied_action": self.applied_action,
        }

    def _collides(self, obstacle):
        # Rectangle/triangle intersection using the maximum triangle height
        # within the player's horizontal interval. Collision matches the art.
        left = self.x + 0.04
        right = self.x + self.player_size - 0.04
        bottom = self.y + 0.04
        for i in range(obstacle.count):
            start = obstacle.x + i * 0.7
            end = start + 0.7
            if right <= start or left >= end:
                continue
            peak = start + 0.35
            closest = min(max(peak, left), right)
            height = obstacle.height * max(0, 1 - abs(closest - peak) / 0.35)
            if bottom < height:
                return True
        return False

    def step(self, action):
        if self._done:
            raise RuntimeError("Call reset() before stepping a finished environment")
        if not self.action_space.contains(action):
            raise ValueError("Action must be 0 (release) or 1 (hold jump)")
        self._inputs.append(int(action))
        self.applied_action = self._inputs.popleft()
        self.steps += 1
        reward = 0.01
        if self.applied_action == 1 and self.grounded:
            self.vy = self.jump_velocity
            self.jumps += 1
        # Two physics substeps avoid passing through narrow hazards.
        for _ in range(2):
            self.x += self.speed * self.dt / 2
            self.vy -= self.gravity * self.dt / 2
            self.y = max(0.0, self.y + self.vy * self.dt / 2)
            if self.grounded:
                self.vy = 0.0
            for obstacle in self.obstacles[self.passed:]:
                if obstacle.x > self.x + self.player_size:
                    break
                if self._collides(obstacle):
                    self.dead = True
                    break
            if self.dead:
                break
        passed = sum(self.x >= o.x + o.width for o in self.obstacles)
        reward += float(passed - self.passed)
        self.passed = passed
        self.success = self.x >= self.level_length and not self.dead
        terminated = self.dead or self.success
        truncated = self.steps >= self.max_steps and not terminated
        if self.dead:
            reward -= 5.0
        if self.success:
            reward += 10.0
        self._done = terminated or truncated
        if self.render_mode == "human":
            self.render()
        return self._observation(), reward, terminated, truncated, self._info()

    def render(self):
        if self.render_mode is None:
            return None
        if self._renderer is None:
            from geodaish.render import Renderer
            self._renderer = Renderer(self.render_mode)
        return self._renderer.draw(self)

    def close(self):
        if self._renderer is not None:
            self._renderer.close()
            self._renderer = None


def heuristic_action(observation):
    """Hand-written reference for checking playability; this is NOT learned."""
    distance = observation[4] * DashEnv.lookahead
    speed = observation[3] * 10
    return int(observation[2] > 0.5 and observation[7] > 0.5
               and -0.1 < distance < speed * 0.18)
