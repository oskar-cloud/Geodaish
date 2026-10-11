"""Geodaish: a compact, reproducible reinforcement learning playground."""

from gymnasium.envs.registration import register

register(id="Geodaish-v0", entry_point="geodaish.env:DashEnv")
