"""Measure the controlled simulator from images, with explicit clock domains."""

import numpy as np

from geodaish.env import SpikeGroup
from geodaish.vision import make_env


def measure_jump(*, input_delay=0, difficulty="normal", physics=None):
    env = make_env(observations="pixels", level="test", input_delay=input_delay,
                   difficulty=difficulty, physics=physics)
    samples, capture_times = [], []
    command_frame = 6
    first_air = None
    landing = None
    try:
        env.reset(seed=0)
        # Set up a clear runway with a visible marker for optical speed.
        # These values are scene preparation only; all measurements use pixels.
        env.unwrapped.obstacles = [SpikeGroup(12.0, 1)]
        env.unwrapped.level_length = 100.0
        env.observer.reset()
        env._capture()
        for frame in range(1, 181):
            _, _, terminated, truncated, _ = env.step(int(frame - 1 == command_frame))
            if terminated or truncated:
                raise ValueError("Calibration hit an obstacle before landing; use the default physics first")
            d = env.detection
            capture_times.append(env.capture_ms)
            samples.append({"frame": frame, "time_seconds": frame / 60,
                            "height": d.height, "speed": d.speed, "grounded": d.grounded})
            if not d.grounded and first_air is None:
                first_air = frame
            elif first_air is not None and d.grounded:
                landing = frame
                break
        if first_air is None or landing is None:
            raise ValueError("Could not observe a complete jump")
        airborne = [s for s in samples if not s["grounded"]]
        times = [(s["frame"] - first_air + 1) / 60 for s in airborne]
        a, b, _ = np.polyfit(times, [s["height"] for s in airborne], 2)
        gravity = float(-2 * a)
        # Match DashEnv's two semi-implicit substeps per decision.
        jump_velocity = float(b + gravity / 240)
        speed = float(np.median([s["speed"] for s in samples if s["speed"] > 0]))
        delay_frames = first_air - command_frame - 1
        return {
            "schema_version": 1,
            "source": "geodaish-rendered-rgb",
            "clock": "simulation frames at 60 Hz; processing time reported separately",
            "pixels_per_unit": env.observer.scale,
            "measurements": {
                "peak_height": max(s["height"] for s in samples),
                "airtime_seconds": (landing - first_air + 1) / 60,
                "command_to_first_motion_ms": (first_air - command_frame) * 1000 / 60,
                "input_delay_frames": delay_frames,
                "capture_and_detection_mean_ms": float(np.mean(capture_times)),
            },
            "training": {"physics": {"speed": speed, "gravity": gravity,
                                     "jump_velocity": jump_velocity}, "input_delay": delay_frames},
            "samples": samples,
        }
    finally:
        env.close()
