"""Automatic retries must not bypass observation checks or the stop latch."""

from types import SimpleNamespace

import numpy as np
import pytest

pytest.importorskip("cv2")

from geodaish.windows.control import JumpController, Stopped
from geodaish.windows.perception import CubeMissing, GroundMissing, UnsupportedObstacle
from geodaish.windows.retry import AttemptRecovery


def scene(*, ready=True, grounded=True, distance=6):
    obs = np.zeros(16, dtype=np.float32)
    obs[4], obs[7] = distance / 16, 1
    return SimpleNamespace(ready=ready, grounded=grounded, observation=obs)


def disappear(recovery, stamp=0):
    recovery.failed(CubeMissing("cube gone"), stamp)
    recovery.failed(CubeMissing("cube gone"), stamp + .05)


def test_waits_for_disappearance_and_stable_safe_respawn():
    recovery = AttemptRecovery()
    recovery.begin()
    # The same moving level after an unsupported obstacle is not a new attempt.
    for t in (0, .05, .1):
        assert not recovery.ready(scene(), t)
    disappear(recovery, .2)
    assert not recovery.ready(scene(), .35)
    assert not recovery.ready(scene(), .4)
    assert recovery.ready(scene(), .45)
    recovery.resumed()
    assert not recovery.waiting


@pytest.mark.parametrize('bad', [scene(ready=False), scene(grounded=False), scene(distance=1)])
def test_never_resumes_on_frozen_airborne_or_imminent_collision_frames(bad):
    recovery = AttemptRecovery()
    recovery.begin()
    disappear(recovery)
    for t in (.1, .15, .2, .25):
        assert not recovery.ready(bad, t)


def test_menu_or_single_missing_frame_is_not_a_retry():
    recovery = AttemptRecovery()
    recovery.begin()
    recovery.failed(CubeMissing('gone'), 0)
    recovery.failed(GroundMissing('menu'), .05)
    recovery.failed(UnsupportedObstacle('block'), .1)
    for t in (.15, .2, .25, .3):
        assert not recovery.ready(scene(), t)
    assert not recovery.saw_disappearance


def test_every_retry_needs_new_evidence_and_frame_gaps_break_confirmation():
    recovery = AttemptRecovery()
    recovery.begin()
    disappear(recovery)
    assert not recovery.ready(scene(), .1)
    assert not recovery.ready(scene(), .15)
    assert not recovery.ready(scene(), 1)  # old evidence of stability expires
    assert not recovery.ready(scene(), 1.05)
    assert recovery.ready(scene(), 1.1)
    recovery.resumed()
    recovery.begin()
    assert not recovery.ready(scene(), 1.15)


class Game:
    jump_vk = 0x26
    def __init__(self):
        self.focus = True
        self.keys = set()
        self.events = []
    def focused(self): return self.focus
    def key_down(self, key): return key in self.keys
    def send_jump(self, down): self.events.append(down)


@pytest.mark.parametrize('stop', ['f9', 'focus', 'button'])
def test_recovery_cannot_rearm_after_stop_even_with_valid_respawn(stop):
    game = Game()
    c = JumpController(game)
    c.arm()
    c.apply(1, c.clock())
    c.suspend('Waiting for next attempt')
    assert game.events == [True, False]
    if stop == 'f9': game.keys.add(0x78)
    elif stop == 'focus': game.focus = False
    else: c.stop('STOP')
    c.check()
    game.focus = True
    game.keys.clear()
    with pytest.raises(Stopped):
        c.arm()
    assert game.events == [True, False]
