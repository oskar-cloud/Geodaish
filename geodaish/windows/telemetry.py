"""Latest-only Windows telemetry. Screenshots require explicit --stream-frames."""

import base64
import io
import os
from pathlib import Path
import time
from uuid import uuid4

from geodaish.dashboard import SnapshotPublisher, utc_now


class LiveReporter:
    def __init__(self, args):
        self.interval = args.report_every
        self.stream_frames = args.stream_frames
        self.last = -float("inf")
        self.last_row = {}
        self.publisher = SnapshotPublisher(args.dashboard_file,
            None if args.local_only else args.dashboard_url or os.environ.get("GEODAISH_DASHBOARD_URL"),
            os.environ.get("GEODAISH_DASHBOARD_TOKEN"), endpoint="/api/windows")
        self.snapshot = {"schemaVersion":1,"source":"geometry-dash-windows",
            "run":{"id":uuid4().hex,"label":Path(args.output).name if args.output else "Windows session",
                   "startedAt":utc_now(),"status":"running","mode":args.mode,"jumpKey":args.jump_key,
                   "model":Path(args.model).name if args.mode=="run" else None},
            "telemetry":{"sequence":0},"scene":None,"image":None}

    def emit(self, stats, controller, row=None, frame=None, scene=None, *, final=False):
        now = time.perf_counter()
        if not final and now-self.last < self.interval:
            return
        self.last = now
        row = (row or {}) if not final else self.last_row
        self.last_row = row
        self.snapshot["run"]["status"] = "stopped" if final else "running"
        self.snapshot["telemetry"] = {
            "sequence":self.snapshot["telemetry"]["sequence"]+1,"updatedAt":utc_now(),
            "elapsedSeconds":float(stats.get("seconds",row.get("time",0))),
            "frames":stats["frames"],"validFrames":stats["valid_frames"],
            "armed":controller.armed,"held":controller.held,"presses":controller.presses,
            "action":row.get("action"),"captureMs":row.get("capture_ms"),"pipelineMs":row.get("pipeline_ms"),
            "reason":str(stats.get("stop_reason") or row.get("error") or controller.reason)[:160]}
        if not final:
            self.snapshot["scene"] = None if scene is None else {
                "width":frame.shape[1],"height":frame.shape[0],"groundY":scene.ground_y,
                "cube":vars(scene.cube),"spikes":[vars(b) for b in scene.spikes[:20]],
                "observation":scene.observation.tolist(),"ready":scene.ready}
            self.snapshot["image"] = None
            if scene is not None and self.stream_frames:
                from PIL import Image
                from geodaish.windows.perception import annotate
                # Only the playfield from just left of the cube forward. Left
                # overlays/HUD are excluded; users must disable other overlays.
                left = max(int(frame.shape[1]*0.28),scene.cube.left-35)
                top = max(50,int(scene.ground_y-4*scene.cube.height))
                pic = Image.fromarray(annotate(frame,scene)).crop((left,top,frame.shape[1],min(frame.shape[0],scene.ground_y+30)))
                pic.thumbnail((960,400))
                buffer = io.BytesIO()
                pic.save(buffer,format="JPEG",quality=65)
                self.snapshot["image"] = "data:image/jpeg;base64,"+base64.b64encode(buffer.getvalue()).decode("ascii")
        self.publisher.publish(self.snapshot)

    def close(self):
        self.publisher.close()
