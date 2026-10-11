"""Fit a single, fully observed real-game jump without assuming simulator physics."""

import math

import numpy as np


def fit_jump(rows):
    sent = next((i for i,r in enumerate(rows) if r.get("sent") and r.get("action") == 1), None)
    if sent is None:
        raise ValueError("No dispatched jump in this log; run windows probe first")
    command = rows[sent]["dispatch_time"]
    if not rows[sent].get("grounded"):
        raise ValueError("Jump command must start on flat ground")
    airborne = []
    landing = None
    for row in rows[sent+1:]:
        if row.get("error") or row.get("observation") is None:
            raise ValueError("Tracking was lost before landing; do not fit death/restart data")
        if row.get("grounded"):
            if airborne:
                landing = row
                break
        else:
            airborne.append(row)
    if landing is None or len(airborne) < 6:
        raise ValueError("Need at least six airborne frames and a confirmed landing")
    t = np.array([r["time"]-command for r in airborne])
    y = np.array([r["height"] for r in airborne])
    if not np.all(np.diff(t)>0) or np.max(np.diff(t)) > 0.25:
        raise ValueError("Jump timestamps have gaps or are not monotonic")
    a,b,c = np.polyfit(t,y,2)
    gravity = float(-2*a)
    roots = np.roots([a,b,c])
    if gravity <= 0 or np.any(np.iscomplex(roots)):
        raise ValueError("Jump does not fit a downward parabola")
    takeoff, fitted_landing = sorted(float(x) for x in roots)
    velocity = float(2*a*takeoff+b)
    residual = float(np.sqrt(np.mean((np.polyval([a,b,c],t)-y)**2)))
    if not (5 < gravity < 200 and 2 < velocity < 35 and residual < 0.12):
        raise ValueError("Implausible/poor jump fit; inspect recorded frames and calibration")
    if abs(takeoff) > 0.25:
        raise ValueError("Fitted takeoff differs too far from command dispatch")
    valid = [r for r in rows[:sent+len(airborne)+2] if r.get("ready")]
    speeds = [r["speed"] for r in valid if r.get("speed",0)>0]
    if not speeds:
        raise ValueError("No measured scrolling speed")
    speed = float(np.median(speeds))
    pipelines = [r["pipeline_ms"] for r in rows if r.get("pipeline_ms") is not None]
    pipeline = float(np.median(pipelines)) if pipelines else 0.0
    # Approximate screen-to-input latency as a simulator action queue. Capture
    # timestamps and sparse samples cannot separate display and OS latency.
    effective_latency = max(0,takeoff)+pipeline/1000
    delay = min(30, max(0, math.ceil(effective_latency*60)))
    # DashEnv's semi-implicit two-substep integrator has v_eff = v - g*dt/4.
    simulator_velocity = velocity+gravity/240
    return {"source":"GeometryDash.exe screen measurements; single-jump estimate",
            "measurements":{"airborne_frames":len(airborne),"speed":speed,"gravity":gravity,
                "jump_velocity":velocity,"peak_height":float(y.max()),
                "fitted_airtime_seconds":fitted_landing-takeoff,"fit_rmse_units":residual,
                "dispatch_to_first_visible_motion_ms":float(t[0]*1000),
                "fitted_dispatch_to_takeoff_ms":takeoff*1000,"median_pipeline_ms":pipeline,
                "median_sample_interval_ms":float(np.median(np.diff(t))*1000)},
            "training":{"physics":{"speed":speed,"gravity":gravity,"jump_velocity":simulator_velocity},
                        "input_delay":delay},
            "limitations":["One jump, colour-based centre estimate and capture timestamps; not ground-truth physics.",
                "Input queue approximates measured latency; live decision cadence/jitter are not reproduced.",
                "Original hitboxes and invisible obstacles may differ; validate in the game after training."],
            "samples":[{"time_after_command":float(ti),"height":float(yi)} for ti,yi in zip(t,y)]}
