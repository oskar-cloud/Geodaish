"""Optional Windows commands; vision/offline tools also run on other hosts."""

import json
from pathlib import Path
import time


def register(sub):
    from geodaish.cli import positive_float
    parser = sub.add_parser("windows", help="Read/control the real Steam game")
    commands = parser.add_subparsers(dest="mode", required=True)
    capture = commands.add_parser("capture", help="Save one client screenshot, no input")
    capture.add_argument("--output", default="runs/windows/screen.png")
    capture.add_argument("--wait", type=positive_float, default=3)
    capture.set_defaults(func=capture_command)
    calibrate = commands.add_parser("calibrate", help="Select a grounded cube and ground on a saved image")
    calibrate.add_argument("--image", required=True)
    calibrate.add_argument("--cube", type=int, nargs=4, metavar=("X", "Y", "WIDTH", "HEIGHT"))
    calibrate.add_argument("--ground-y", type=int)
    calibrate.add_argument("--output", default="runs/windows/profile.json")
    calibrate.set_defaults(func=calibrate_command)
    detect = commands.add_parser("detect", help="Annotate one saved image, no input")
    detect.add_argument("--image", required=True)
    detect.add_argument("--profile", required=True)
    detect.add_argument("--output", default="runs/windows/detected.png")
    detect.set_defaults(func=detect_command)
    for mode in ("preview", "run", "probe"):
        p = commands.add_parser(mode, help={"preview":"Live visual inspection, never sends keys",
            "run":"Explicitly arm PPO with F8, stop with F9", "probe":"Arm one isolated calibration jump with F8"}[mode])
        p.add_argument("--profile", required=True)
        p.add_argument("--model", default="models/demo-normal.zip")
        p.add_argument("--jump-key", choices=["space","up"], default="space", help="Choose the game's enabled jump binding")
        p.add_argument("--seconds", type=positive_float, default=60 if mode == "probe" else 600)
        p.add_argument("--fps", type=positive_float, default=30)
        p.add_argument("--output")
        p.add_argument("--headless", action="store_true")
        p.add_argument("--record-frames", action="store_true", help="Save local screenshots for visual review")
        p.add_argument("--dashboard-file", default="runs/windows-live.json")
        p.add_argument("--dashboard-url", help="Vercel site URL; alternatively GEODAISH_DASHBOARD_URL")
        p.add_argument("--local-only", action="store_true", help="Disable all uploads, including environment-configured URLs")
        p.add_argument("--report-every", type=positive_float, default=1)
        p.add_argument("--stream-frames", action="store_true", help="Publish cropped game images as well as detected geometry")
        if mode != "preview":
            p.add_argument("--arm-after", type=positive_float, help="Explicit automatic arming delay; otherwise F8/button required")
        else:
            p.set_defaults(arm_after=None)
        p.set_defaults(func=session_command)
        if mode == "run":
            p.add_argument("--single-attempt", action="store_true",
                           help="Stop after a lost cube/unsupported section instead of waiting for Auto-Retry")
    measure = commands.add_parser("measure", help="Fit a complete probe jump; create a simulator training profile")
    measure.add_argument("--log", required=True)
    measure.add_argument("--output", default="runs/windows/physics.json")
    measure.set_defaults(func=measure_command)


def capture_command(args):
    from PIL import Image
    from geodaish.windows.native import WindowsGame, GameCapture
    print(f"Select Geometry Dash; capturing in {args.wait:g} seconds. No keys are sent.", flush=True)
    time.sleep(args.wait)
    game = WindowsGame()
    if not game.focused():
        raise ValueError("Select Geometry Dash before capturing")
    capture = GameCapture(game)
    try:
        frame, _, _ = capture.grab()
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.fromarray(frame).save(path)
        print(path)
    finally:
        capture.close()


def read_image(path):
    import numpy as np
    from PIL import Image
    return np.asarray(Image.open(path).convert("RGB"))


def calibrate_command(args):
    import cv2
    from geodaish.windows.perception import Profile
    frame = read_image(args.image)
    cube, ground = args.cube, args.ground_y
    try:
        if cube is None:
            cube = cv2.selectROI("Select whole upright cube, then ENTER", cv2.cvtColor(frame, cv2.COLOR_RGB2BGR), False)
            cv2.destroyAllWindows()
            if not cube[2] or not cube[3]:
                raise ValueError("Cube selection cancelled")
        if ground is None:
            selected = []
            title = "Click the TOP of the flat ground line; Q cancels"
            cv2.namedWindow(title)
            cv2.setMouseCallback(title, lambda event,x,y,flags,param: selected.append(y) if event == cv2.EVENT_LBUTTONDOWN else None)
            cv2.imshow(title, cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))
            while not selected:
                if cv2.waitKey(50) & 0xFF in (ord("q"), 27) or cv2.getWindowProperty(title, cv2.WND_PROP_VISIBLE) < 1:
                    raise ValueError("Ground selection cancelled")
            ground = selected[0]
        profile = Profile.from_selection(frame, cube, ground)
        profile.save(args.output)
        print(f"Profile: {args.output}; now verify with windows detect and windows preview")
    finally:
        cv2.destroyAllWindows()


def detect_command(args):
    from PIL import Image
    from geodaish.windows.perception import Observer, Profile, annotate
    frame = read_image(args.image)
    scene = Observer(Profile.load(args.profile)).observe(frame, 0.0)
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(annotate(frame,scene)).save(path)
    print(json.dumps({"cube":vars(scene.cube), "spikes":[vars(box) for box in scene.spikes],
                      "observation":scene.observation.tolist(), "ready":scene.ready, "annotated":str(path)},indent=2))


def session_command(args):
    from geodaish.windows.runtime import run_session
    from datetime import datetime
    while run_session(args):
        # A retry is a fresh, explicitly armed session with a separate report.
        args.arm_after = None
        if args.output:
            path = Path(args.output)
            args.output = str(path.with_name(f"{path.name}-retry-{datetime.now():%H%M%S%f}"))


def measure_command(args):
    from geodaish.windows.measurement import fit_jump
    rows = [json.loads(line) for line in Path(args.log).read_text(encoding="utf-8").splitlines() if line.strip()]
    report = fit_jump(rows)
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    print(json.dumps(report,indent=2))
    print(f"Use --physics-profile {path} with train/evaluate. Estimates need repeated live validation.")
