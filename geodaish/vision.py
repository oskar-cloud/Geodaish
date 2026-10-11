"""Pixel-only observations for the controlled Geodaish test scene.

The palette, viewport and pixel scale are camera calibration, not game state.
This detector is deliberately specific to our renderer, not Geometry Dash.
"""

from dataclasses import dataclass
import time

import gymnasium as gym
import numpy as np

from geodaish.env import DashEnv


class PerceptionError(ValueError):
    """The current image cannot safely be turned into an observation."""


@dataclass(frozen=True)
class Box:
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self):
        return self.right - self.left

    @property
    def height(self):
        return self.bottom - self.top


@dataclass(frozen=True)
class Detection:
    cube: Box
    spikes: tuple[Box, ...]
    ground: int
    height: float
    vertical_speed: float
    speed: float
    grounded: bool


def _boxes(mask, y_offset, join=0):
    columns = np.flatnonzero(mask.any(axis=0))
    if not len(columns):
        return []
    groups = np.split(columns, np.flatnonzero(np.diff(columns) > join + 1) + 1)
    result = []
    for group in groups:
        left, right = int(group[0]), int(group[-1]) + 1
        rows = np.flatnonzero(mask[:, left:right].any(axis=1))
        result.append(Box(left, int(rows[0]) + y_offset, right, int(rows[-1]) + y_offset + 1))
    return result


def _solid_regions(mask, size=7):
    """Remove thin decoration (finish flag/text) before locating the cube."""
    height, width = mask.shape
    if height < size or width < size:
        return np.zeros((0, 0), dtype=bool)
    horizontal = mask[:, :width - size + 1].copy()
    for offset in range(1, size):
        horizontal &= mask[:, offset:width - size + 1 + offset]
    solid = horizontal[:height - size + 1].copy()
    for offset in range(1, size):
        solid &= horizontal[offset:height - size + 1 + offset]
    return solid


class PixelObserver:
    def __init__(self, pixels_per_unit=68.0, viewport_top=150):
        if not np.isfinite(pixels_per_unit) or pixels_per_unit <= 0:
            raise ValueError("pixels_per_unit must be positive and finite")
        self.scale = pixels_per_unit
        self.viewport_top = viewport_top
        self.reset()

    def reset(self):
        self.previous = None
        self.previous_time = None
        self.previous_height = None
        self.speed = 0.0

    def observe(self, frame, timestamp):
        if (not isinstance(frame, np.ndarray) or frame.dtype != np.uint8
                or frame.ndim != 3 or frame.shape[2] != 3):
            raise PerceptionError("Expected an H x W x 3 uint8 RGB screenshot")
        if not np.isfinite(timestamp) or (self.previous_time is not None and timestamp <= self.previous_time):
            raise PerceptionError("Screenshot timestamps must increase; reset the observer between attempts")
        roi = frame[self.viewport_top:]
        green = ((roi[:, :, 0] >= 72) & (roi[:, :, 0] <= 112)
                 & (roi[:, :, 1] >= 210) & (roi[:, :, 1] <= 250)
                 & (roi[:, :, 2] >= 165) & (roi[:, :, 2] <= 205))
        ground_rows = np.flatnonzero(green.sum(axis=1) > frame.shape[1] * 0.55)
        if not len(ground_rows):
            raise PerceptionError("Ground line not found in the test-scene screenshot")
        ground_index = int(ground_rows[0])
        ground = ground_index + self.viewport_top
        # Erosion removes 6 pixels from each bounding box's extent. Restore
        # that extent to keep distances and jump height in screenshot pixels.
        regions = _boxes(_solid_regions(green[:ground_index]), self.viewport_top)
        candidates = [Box(box.left, box.top, box.right + 6, box.bottom + 6) for box in regions
                      if box.width >= 15 and 0.85 < box.width / box.height < 1.15]
        if len(candidates) != 1:
            raise PerceptionError(f"Expected one cube, found {len(candidates)}")
        cube = candidates[0]
        scene = roi[:ground_index]
        pink = ((scene[:, :, 0] >= 235) & (scene[:, :, 1] >= 92)
                & (scene[:, :, 1] <= 132) & (scene[:, :, 2] >= 126)
                & (scene[:, :, 2] <= 166))
        spikes = tuple(box for box in _boxes(pink, self.viewport_top, join=2)
                       if box.height >= 8 and abs(box.bottom - ground) <= 2)
        height = max(0.0, (ground - cube.bottom) / self.scale)
        grounded = ground - cube.bottom <= 2
        if grounded:
            height = 0.0
        vy = 0.0
        if self.previous is not None:
            dt = timestamp - self.previous_time
            vy = (height - self.previous.height) / dt
            # Estimate endpoint velocity instead of the interval's average.
            if self.previous_height is not None:
                old_height, old_dt = self.previous_height
                old_vy = (self.previous.height - old_height) / old_dt
                vy += (vy - old_vy) * dt / (dt + old_dt)
            shifts = []
            for before in self.previous.spikes:
                matches = [after for after in spikes
                           if abs(after.width - before.width) <= 2
                           and 0 <= before.left - after.left <= self.scale * 15 * dt + 2]
                if matches:
                    after = min(matches, key=lambda box: abs(before.left - box.left))
                    shifts.append((before.left - after.left + cube.left - self.previous.cube.left) / self.scale / dt)
            if shifts:
                self.speed = float(np.median(shifts))
            self.previous_height = (self.previous.height, dt)
        if grounded:
            vy = 0.0
        detection = Detection(cube, spikes, ground, height, vy, self.speed, grounded)
        observation = np.zeros(16, dtype=np.float32)
        observation[:4] = (height / 3, vy / 12, float(grounded), self.speed / 10)
        upcoming = [box for box in spikes if box.right > cube.left]
        for i, box in enumerate(upcoming[:3]):
            distance = (box.left - cube.right) / self.scale
            if distance <= 16:
                observation[4 + 4 * i:8 + 4 * i] = (
                    distance / 16, box.width / self.scale / 3, box.height / self.scale / 2, 1)
        self.previous, self.previous_time = detection, timestamp
        return np.clip(observation, -1, 1), detection


class PixelEnv(gym.Wrapper):
    """Capture -> detect -> policy observation; actions use DashEnv's jump input.

    Reward and termination still belong to the simulator. Its exact state never
    enters the policy observation. Terminal frames need no subsequent decision.
    """

    def __init__(self, env, display=False):
        super().__init__(env)
        self.observer = PixelObserver()
        self.display = display
        self.screen = None
        self.clock = None
        self.frame = None
        self.detection = None
        self.frame_index = 0
        self.capture_ms = 0.0

    def _capture(self, terminal=False):
        started = time.perf_counter()
        self.frame = self.env.render()
        self.detection = None
        if terminal:
            obs = np.zeros(16, dtype=np.float32)
        else:
            obs, self.detection = self.observer.observe(self.frame, self.frame_index / 60)
        self.capture_ms = (time.perf_counter() - started) * 1000
        if self.display:
            self.render()
        return obs

    def reset(self, **kwargs):
        _, info = self.env.reset(**kwargs)
        self.observer.reset()
        self.frame_index = 0
        return self._capture(), {**info, "vision_valid": True}

    def step(self, action):
        _, reward, terminated, truncated, info = self.env.step(action)
        self.frame_index += 1
        # Time limits must keep the real final observation for PPO's bootstrap.
        obs = self._capture(terminated)
        return obs, reward, terminated, truncated, {**info, "vision_valid": self.detection is not None}

    def annotated_frame(self):
        import pygame
        surface = pygame.surfarray.make_surface(np.transpose(self.frame, (1, 0, 2)))
        if self.detection is not None:
            for box in (self.detection.cube, *self.detection.spikes):
                pygame.draw.rect(surface, (255, 213, 92),
                                 (box.left, box.top, box.width, box.height), 2)
        # An overlay for the human observer only, drawn after pixel extraction.
        held = self.env.unwrapped.applied_action == 1
        label = "JUMP / HELD" if held else "JUMP / RELEASED"
        font = pygame.font.Font(None, 24)
        surface.blit(font.render(label, True, (92, 230, 185) if held else (180, 194, 215)), (485, 512))
        return np.transpose(pygame.surfarray.array3d(surface), (1, 0, 2))

    def render(self):
        if not self.display:
            return self.frame
        import pygame
        if self.screen is None:
            pygame.display.init()
            self.screen = pygame.display.set_mode((self.frame.shape[1], self.frame.shape[0]))
            pygame.display.set_caption("GEODAISH / Pixel observations / yellow = detected objects")
            self.clock = pygame.time.Clock()
        pygame.surfarray.blit_array(self.screen, np.transpose(self.annotated_frame(), (1, 0, 2)))
        pygame.display.flip()
        self.clock.tick(60)
        return self.frame

    def close(self):
        if self.screen is not None:
            import pygame
            pygame.display.quit()
            self.screen = None
        self.env.close()


def make_env(*, observations="state", render_mode=None, **kwargs):
    if observations not in ("state", "pixels"):
        raise ValueError("observations must be state or pixels")
    if observations == "pixels":
        return PixelEnv(DashEnv(render_mode="rgb_array", **kwargs), display=render_mode == "human")
    return DashEnv(render_mode=render_mode, **kwargs)
