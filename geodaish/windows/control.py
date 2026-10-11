"""Input ownership, foreground checks, latching stop and independent watchdog."""

import threading
import time


class Stopped(RuntimeError):
    pass


class JumpController:
    def __init__(self, game, *, timeout=0.35, clock=time.perf_counter):
        self.game = game
        self.timeout = timeout
        self.clock = clock
        self.lock = threading.RLock()
        self.armed = False
        self.session_active = False
        self.held = False
        self.stopped = False
        self.reason = "Not armed"
        self.heartbeat = clock()
        self.presses = 0
        self.releases = 0

    def arm(self):
        with self.lock:
            if self.stopped:
                raise Stopped(self.reason)
            if not self.game.focused():
                raise Stopped("Select Geometry Dash before arming")
            if self.game.key_down(self.game.jump_vk):
                raise Stopped("Release the physical jump key before arming")
            self.armed = True
            self.session_active = True
            self.reason = "Armed"
            self.heartbeat = self.clock()

    def apply(self, action, frame_time):
        with self.lock:
            if self.stopped or not self.armed:
                raise Stopped(self.reason)
            if action not in (0,1):
                self.stop("Invalid model action")
                raise Stopped(self.reason)
            if not self.game.focused():
                self.stop("Game lost focus")
                raise Stopped(self.reason)
            if not 0 <= self.clock()-frame_time <= self.timeout:
                self.stop("Stale frame or slow model decision")
                raise Stopped(self.reason)
            self.heartbeat = self.clock()
            desired = bool(action)
            if desired != self.held:
                # Set ownership before the API call so failures also clean up.
                if desired:
                    self.held = True
                try:
                    self.game.send_jump(desired)
                except Exception:
                    self.stop("Keyboard delivery failed")
                    raise
                self.held = desired
                self.presses += int(desired)
                self.releases += int(not desired)

    def suspend(self, reason="Waiting between attempts"):
        """Release ownership while PPO updates; retain focus and F9 monitoring."""
        with self.lock:
            if self.stopped:
                raise Stopped(self.reason)
            if self.held:
                self.game.send_jump(False)
                self.held = False
                self.releases += 1
            self.armed = False
            self.reason = reason

    def stop(self, reason="Stopped by user"):
        with self.lock:
            if not self.stopped:
                self.reason = reason
            self.stopped = True
            self.armed = False
            if self.held:
                # A key-up is the sole event allowed after focus is lost.
                self.game.send_jump(False)
                self.held = False
                self.releases += 1

    def check(self):
        with self.lock:
            if self.game.key_down(0x78):  # F9; never ESC (also used by Computer Use)
                self.stop("F9 emergency stop")
            elif self.session_active and not self.game.focused():
                self.stop("Game lost focus")
            elif self.armed and self.clock()-self.heartbeat > self.timeout:
                self.stop("Watchdog: capture/inference stalled")


class Watchdog:
    def __init__(self, controller):
        self.controller = controller
        self.closed = threading.Event()
        self.ready = threading.Event()
        self.error = None
        self.thread = threading.Thread(target=self._run, daemon=True, name="geodaish-stop")

    def _run(self):
        registered = False
        try:
            self.controller.game.register_stop()
            registered = True
            self.ready.set()
            while not self.closed.wait(0.01):
                if self.controller.game.stop_requested():
                    self.controller.stop("F9 emergency stop")
                self.controller.check()
        except Exception as exc:
            self.error = exc
            with self.controller.lock:
                self.controller.stopped = True
                self.controller.armed = False
                self.controller.reason = f"Watchdog/input error: {exc}"
        finally:
            self.ready.set()
            if registered:
                self.controller.game.unregister_stop()

    def start(self):
        self.thread.start()
        if not self.ready.wait(timeout=2) or self.error:
            raise Stopped(f"Stop watchdog could not start: {self.error}")

    def close(self):
        try:
            self.controller.stop("Session ended")
        finally:
            self.closed.set()
            self.thread.join(timeout=1)
