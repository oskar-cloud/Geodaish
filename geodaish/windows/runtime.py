"""Live preview and bounded PPO sessions. No automatic menu or restart input."""

from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
import queue
import threading
import time

import numpy as np
from PIL import Image

from geodaish.vision import PerceptionError
from geodaish.windows.control import JumpController, Stopped, Watchdog
from geodaish.windows.native import GameCapture, WindowsGame
from geodaish.windows.perception import Observer, Profile, annotate
from geodaish.windows.telemetry import LiveReporter


def run_session(args):
    profile = Profile.load(args.profile)
    import cv2
    cv2.setNumThreads(1)  # avoid OpenCV oversubscribing CPU while the game renders
    game = WindowsGame(jump_key=args.jump_key)
    model = None
    controls_enabled = args.mode in ("run", "probe")
    if args.mode == "run":
        from geodaish.cli import load_model
        model = load_model(args.model)
        if model.observation_space.shape != (16,) or getattr(model.action_space,"n",None) != 2:
            raise ValueError("Model must accept 16 observations and two jump actions")
        model.predict(np.zeros(16,dtype=np.float32),deterministic=True)  # warm-up before arming
    output = Path(args.output or f"runs/windows/{datetime.now():%Y%m%d-%H%M%S}-{args.mode}")
    if output.exists() and any(output.iterdir()):
        raise ValueError(f"{output} is not empty; choose a new output directory")
    output.mkdir(parents=True,exist_ok=True)
    stop = threading.Event()
    finished = threading.Event()
    arm = threading.Event()
    updates = queue.Queue(maxsize=1)
    controller = JumpController(game)
    guard = Watchdog(controller)
    reporter = LiveReporter(args)
    started = time.perf_counter()
    stats = {"source":"GeometryDash.exe client screen", "mode":args.mode,
             "jump_key":args.jump_key,
             "started_at":datetime.now(timezone.utc).isoformat(), "profile":asdict(profile),
             "model":str(args.model) if model else None, "frames":0, "valid_frames":0,
             "armed_frames":0, "stop_reason":None, "presses":0,"releases":0}

    def publish(frame, scene, status):
        if args.headless:
            return
        annotated = annotate(frame,scene,status) if frame is not None else status
        try:
            updates.get_nowait()
        except queue.Empty:
            pass
        updates.put_nowait(annotated)

    def worker():
        capture = None
        observer = Observer(profile)
        arm_key_was_down = False
        active = False
        first_valid_saved = False
        probe_started = None
        probe_airborne = False
        try:
            capture = GameCapture(game)  # MSS context belongs to this thread
            guard.start()
            with (output/"frames.jsonl").open("w",encoding="utf-8",buffering=1) as log:
                while not stop.is_set() and not controller.stopped:
                    tick = time.perf_counter()
                    if tick-started >= args.seconds:
                        controller.stop("Time limit reached")
                        break
                    key_down = game.key_down(0x77)  # F8 explicitly arms
                    if key_down and not arm_key_was_down and controls_enabled:
                        arm.set()
                    arm_key_was_down = key_down
                    if args.arm_after is not None and tick-started >= args.arm_after and controls_enabled:
                        arm.set()
                    # A preview may be occluded; it cannot send input. Live
                    # control checks focus before capture, inference and dispatch.
                    if controller.armed and not game.focused():
                        raise Stopped("Game lost focus")
                    if not game.focused():
                        observer.reset()
                        publish(None,None,"Select Geometry Dash to start screen capture (F9 stops)")
                        reporter.emit(stats,controller,{"time":tick-started,"error":"Select Geometry Dash; waiting for foreground"})
                        stop.wait(0.1)
                        continue
                    frame, stamp, capture_time = capture.grab()
                    stats["frames"] += 1
                    row = {"time":stamp-started,"capture_ms":capture_time*1000,
                           "observation":None,"action":None,"sent":False,"error":None}
                    scene = None
                    try:
                        if not controller.armed:
                            fitted = profile.resized(frame.shape[1], frame.shape[0])
                            if fitted != observer.profile:
                                observer = Observer(fitted)
                                stats["effective_profile"] = asdict(fitted)
                        scene = observer.observe(frame,stamp)
                        stats["valid_frames"] += 1
                        row.update(observation=scene.observation.tolist(),height=scene.height,
                                   speed=scene.speed,grounded=scene.grounded,ready=scene.ready,
                                   cube=vars(scene.cube),spikes=[vars(b) for b in scene.spikes])
                        probe_clear = args.mode != "probe" or (scene.grounded and scene.observation[7] == 1 and scene.observation[4]*16 >= 6)
                        if controls_enabled and arm.is_set() and not controller.armed and scene.ready and probe_clear and game.focused():
                            controller.arm()
                            arm.clear()
                        if not first_valid_saved and scene.spikes:
                            Image.fromarray(annotate(frame,scene)).save(output/"detections.png")
                            first_valid_saved = True
                        if controller.armed:
                            if active and not scene.ready:
                                raise Stopped("Scene stopped moving or lost reliable tracking")
                            if scene.ready:
                                active = True
                                if args.mode == "probe":
                                    if probe_started is None:
                                        # Probe only in a clearly empty approach to a visible spike.
                                        if not scene.grounded or scene.observation[4]*16 < 6:
                                            raise Stopped("Probe needs a grounded cube and at least 6 units of clear ground")
                                        probe_started = time.perf_counter()
                                    probe_airborne |= not scene.grounded
                                    if probe_airborne and scene.grounded:
                                        raise Stopped("Probe jump completed and landed")
                                    if time.perf_counter()-probe_started > 2:
                                        raise Stopped("Probe did not complete a visible jump within 2 seconds")
                                    action = int(time.perf_counter()-probe_started < 0.12)
                                else:
                                    action = int(model.predict(scene.observation,deterministic=True)[0])
                            else:
                                action = 0  # waiting for optical speed; no guessed state
                            controller.apply(action,stamp-capture_time)
                            row.update(action=action,sent=True,dispatch_time=time.perf_counter()-started,
                                       pipeline_ms=(time.perf_counter()-stamp+capture_time)*1000)
                            stats["armed_frames"] += 1
                        status = (f"{args.mode.upper()} ACTIVE - F9 STOP" if active else "ARMED - waiting for moving spikes") if controller.armed else "PREVIEW - F8 to arm" if controls_enabled else "PREVIEW ONLY - no keyboard input"
                    except PerceptionError as exc:
                        row["error"] = str(exc)
                        observer.reset()
                        status = str(exc)
                        if controller.armed:
                            raise Stopped(status) from exc
                    finally:
                        if args.record_frames:
                            Image.fromarray(frame).save(output/f"frame-{stats['frames']:05d}.png")
                        log.write(json.dumps(row,allow_nan=False)+"\n")
                        reporter.emit(stats,controller,row,frame,scene)
                    publish(frame,scene,status)
                    stop.wait(max(0,1/args.fps-(time.perf_counter()-tick)))
        except Exception as exc:
            stats["stop_reason"] = str(exc)
            try:
                controller.stop(str(exc))
            except Exception as release_error:
                stats["release_error"] = str(release_error)
        finally:
            try:
                guard.close() if guard.thread.ident is not None else controller.stop("Session ended")
            except Exception as exc:
                stats["release_error"] = str(exc)
            if capture:
                try:
                    capture.close()
                except Exception as exc:
                    stats["capture_close_error"] = str(exc)
            stats.update(stop_reason=stats["stop_reason"] or controller.reason,
                         presses=controller.presses,releases=controller.releases,
                         key_released=not controller.held,seconds=time.perf_counter()-started)
            stop.set()
            try:
                (output/"summary.json").write_text(json.dumps(stats,indent=2)+"\n",encoding="utf-8")
                reporter.emit(stats,controller,final=True)
            except Exception as exc:
                stats["report_error"] = str(exc)
            finally:
                try:
                    reporter.close()
                finally:
                    finished.set()

    thread = threading.Thread(target=worker,name="geodaish-capture")
    restart = False
    if args.headless:
        thread.start()
        try:
            while not finished.wait(0.1):
                pass
        except KeyboardInterrupt:
            stop.set()
            controller.stop("Ctrl+C")
        finally:
            thread.join(timeout=3)
    else:
        from geodaish.windows.window import session_window
        def halt():
            try:
                controller.stop("STOP button / window closed")
            finally:
                stop.set()
        thread.start()
        try:
            restart = session_window(title="Geodaish / Windows pixel control", updates=updates,
                finished=finished, on_stop=halt, on_arm=arm.set if controls_enabled else None,
                result=stats, report_path=output / "summary.json")
        finally:
            if not finished.is_set():
                halt()
            thread.join(timeout=3)
            # Dispose old Tk widget/callback cycles on the main thread before
            # another session starts a capture worker that could trigger GC.
            import gc
            gc.collect()
    print(json.dumps(stats,indent=2))
    print(f"Session report: {output / 'summary.json'}")
    return restart
