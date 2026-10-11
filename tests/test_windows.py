import ctypes
import sys

import numpy as np
import pytest

from geodaish.windows.control import JumpController, Stopped
from geodaish.windows.measurement import fit_jump


class Game:
    jump_vk = 0x20
    def __init__(self):
        self.focus = True
        self.keys = set()
        self.events = []

    def focused(self):
        return self.focus

    def key_down(self, key):
        return key in self.keys

    def send_jump(self, down):
        self.events.append(down)


@pytest.mark.parametrize("stop", ["focus", "f9", "watchdog", "button", "stale"])
def test_owned_key_released_and_stop_latches(stop):
    game, now = Game(), [1.0]
    c = JumpController(game, clock=lambda:now[0])
    c.arm()
    c.apply(1,1)
    c.apply(1,1)
    assert game.events == [True]
    if stop == "focus":
        game.focus = False
    elif stop == "f9":
        game.keys.add(0x78)
    elif stop == "watchdog":
        now[0] += 0.5
    elif stop == "button":
        c.stop("button")
    else:
        with pytest.raises(Stopped):
            c.apply(1,0)
    c.check()
    assert c.stopped and not c.held
    assert game.events == [True,False]
    with pytest.raises(Stopped):
        c.arm()
    with pytest.raises(Stopped):
        c.apply(1,now[0])


def test_preview_and_failed_arm_never_send_keys():
    game = Game()
    c = JumpController(game)
    c.check()
    game.keys.add(0x20)
    with pytest.raises(Stopped):
        c.arm()
    c.stop()
    assert not game.events


def test_watchdog_consumes_queued_short_hotkey_and_releases():
    import threading
    from geodaish.windows.control import Watchdog
    game=Game()
    pending=threading.Event()
    unregistered=[]
    game.register_stop=lambda:None
    game.stop_requested=lambda:pending.is_set()
    game.unregister_stop=lambda:unregistered.append(True)
    c=JumpController(game)
    guard=Watchdog(c)
    guard.start()
    c.arm()
    c.apply(1,c.clock())
    pending.set()
    guard.thread.join(timeout=0.05)
    assert c.stopped and c.reason=='F9 emergency stop' and game.events==[True,False]
    guard.close()
    assert unregistered==[True]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows ABI")
def test_sendinput_union_size():
    from geodaish.windows.native import INPUT
    assert ctypes.sizeof(INPUT) == (40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28)


def scene_image(spike_x=600):
    cv2 = pytest.importorskip("cv2")
    image = np.zeros((450,800,3),dtype=np.uint8)
    image[:]=(20,25,110)
    image[300:303,:]=(255,255,255)
    image[260:300,250:290]=(255,125,0)
    cv2.polylines(image,[np.array([[spike_x,299],[spike_x+20,260],[spike_x+40,299]])],True,(255,255,255),2)
    return image


def test_vision_matches_env_units_and_tracks_scroll():
    pytest.importorskip("cv2")
    from geodaish.windows.perception import Observer, Profile
    p=Profile.from_selection(scene_image(),(250,260,40,40),300)
    o=Observer(p)
    o.observe(scene_image(),0)
    o.observe(scene_image(580),0.05)
    scene=o.observe(scene_image(560),0.1)
    assert scene.ready
    assert scene.speed == pytest.approx(8)
    assert scene.grounded
    assert scene.observation.shape == (16,)
    assert scene.observation.dtype == np.float32
    assert scene.observation[:4] == pytest.approx([0,0,1,0.8])
    assert scene.observation[4] == pytest.approx((559-290)/50/16,abs=0.005)
    assert scene.observation[7] == 1
    assert not np.any(scene.observation[8:])


def test_vision_rejects_menu_missing_cube_and_resize():
    pytest.importorskip("cv2")
    from geodaish.windows.perception import Observer, Profile
    from geodaish.vision import PerceptionError
    o=Observer(Profile.from_selection(scene_image(),(250,260,40,40),300))
    for frame in (np.zeros((450,800,3),dtype=np.uint8),scene_image()[:400]):
        with pytest.raises(PerceptionError):
            o.observe(frame,1)
    frame=scene_image()
    frame[260:300,250:290]=(20,25,110)
    with pytest.raises(PerceptionError,match="one cube"):
        o.observe(frame,1)
    # A debug hitbox remains visible during a death animation. It is not a cube.
    import cv2
    cv2.rectangle(frame,(250,260),(290,299),(255,125,0),1)
    with pytest.raises(PerceptionError,match="one cube"):
        o.observe(frame,1)


def test_proportional_resize_preserves_physical_observations():
    cv2 = pytest.importorskip("cv2")
    from geodaish.windows.perception import Observer, Profile
    from geodaish.vision import PerceptionError
    p = Profile.from_selection(scene_image(), (250,260,40,40), 300)
    resized = p.resized(1200,675)
    assert resized.cube_px == 60 and resized.ground_y == 450
    original = Observer(p)
    larger = Observer(resized)
    for stamp, x in [(0,600),(.05,580),(.1,560)]:
        a = original.observe(scene_image(x), stamp)
        b = larger.observe(cv2.resize(scene_image(x), (1200,675), interpolation=cv2.INTER_NEAREST), stamp)
    assert b.ready and b.observation == pytest.approx(a.observation, abs=.02)
    with pytest.raises(PerceptionError, match="aspect ratio"):
        p.resized(800,400)


def test_update_suspend_releases_key_but_still_monitors_focus():
    game = Game()
    now = [1.0]
    c = JumpController(game, clock=lambda:now[0])
    c.arm()
    c.apply(1,1)
    c.suspend("PPO update")
    now[0] = 20
    c.check()
    assert not c.stopped and not c.held and game.events == [True, False]
    game.focus = False
    c.check()
    assert c.stopped and c.reason == "Game lost focus"


def test_live_report_is_local_geometry_by_default_and_stops(tmp_path,monkeypatch):
    pytest.importorskip("cv2")
    from types import SimpleNamespace
    import json
    from geodaish.windows.telemetry import LiveReporter
    from geodaish.windows.perception import Profile,Observer
    monkeypatch.delenv("GEODAISH_DASHBOARD_URL",raising=False)
    file=tmp_path/'live.json'
    args=SimpleNamespace(report_every=1,stream_frames=False,dashboard_file=file,dashboard_url=None,
                         output=str(tmp_path/'test'),mode='run',model='models/demo-normal.zip',jump_key='up',local_only=True)
    monkeypatch.setenv("GEODAISH_DASHBOARD_URL","https://must-not-contact.example")
    reporter=LiveReporter(args)
    image=scene_image()
    scene=Observer(Profile.from_selection(image,(250,260,40,40),300)).observe(image,0)
    controller=JumpController(Game())
    stats={'frames':1,'valid_frames':1}
    reporter.emit(stats,controller,{'time':1},image,scene)
    data=json.loads(file.read_text())
    assert data['image'] is None and len(data['scene']['observation'])==16
    assert data['run']['model']=='demo-normal.zip'
    controller.stop('F9 emergency stop')
    reporter.emit(stats,controller,final=True)
    reporter.close()
    data=json.loads(file.read_text())
    assert data['run']['status']=='stopped'
    assert not data['telemetry']['held']
    assert data['telemetry']['reason']=='F9 emergency stop'


def jump_rows():
    rows=[dict(time=0,dispatch_time=0,grounded=True,sent=True,action=1,observation=[0]*16,ready=True,speed=8,pipeline_ms=40)]
    for t in np.arange(0.05,0.75,0.05):
        height=max(0,12*(t-0.02)-18*(t-0.02)**2)
        rows.append(dict(time=float(t),height=height,grounded=height==0,observation=[0]*16,ready=True,speed=8))
    return rows


def test_measurement_fits_complete_jump_and_rejects_death():
    rows=jump_rows()
    report=fit_jump(rows)
    assert report["training"]["physics"]["gravity"] == pytest.approx(36)
    assert report["training"]["physics"]["jump_velocity"] == pytest.approx(12.15)
    assert report["training"]["input_delay"] == 4
    broken=rows[:8]+[{"error":"Cube missing"}]
    with pytest.raises(ValueError,match="Tracking was lost"):
        fit_jump(broken)
    with pytest.raises(ValueError,match="confirmed landing"):
        fit_jump(rows[:8])
