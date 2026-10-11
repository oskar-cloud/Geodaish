"""Recover between attempts without undoing a latched user/safety stop."""

from geodaish.windows.perception import CubeMissing


class AttemptRecovery:
    def __init__(self):
        self.waiting = False
        self.missing_frames = 0
        self.saw_disappearance = False
        self.ready_frames = 0
        self.last_stamp = None

    def begin(self):
        self.waiting = True
        self.missing_frames = 0
        self.saw_disappearance = False
        self.ready_frames = 0
        self.last_stamp = None

    def failed(self, error, stamp):
        self.ready_frames = 0
        consecutive = self.last_stamp is not None and 0 < stamp - self.last_stamp <= 0.25
        if isinstance(error, CubeMissing):
            self.missing_frames = self.missing_frames + 1 if consecutive else 1
            self.saw_disappearance |= self.missing_frames >= 2
        else:
            self.missing_frames = 0
        self.last_stamp = stamp

    def ready(self, scene, stamp):
        consecutive = self.last_stamp is not None and 0 < stamp - self.last_stamp <= 0.25
        self.last_stamp = stamp
        self.missing_frames = 0
        # Require disappearance followed by stable, moving flat-ground play.
        # A menu, frozen frame, explosion particle or unknown obstacle cannot
        # resume control. No restart keys or menu clicks are ever generated.
        clear = (scene.ready and scene.grounded and scene.observation[7] == 1
                 and scene.observation[4] * 16 >= 2.5)
        if not (self.waiting and self.saw_disappearance and clear):
            self.ready_frames = 0
            return False
        self.ready_frames = self.ready_frames + 1 if consecutive else 1
        return self.ready_frames >= 3

    def resumed(self):
        self.waiting = False
