"""Calibrated cube/bright-outline spike detection for flat, normal-gravity play.

No game memory, seed, level geometry or simulator state is read here.
"""

from dataclasses import asdict, dataclass
import json
from pathlib import Path

import cv2
import numpy as np

from geodaish.vision import Box, PerceptionError


@dataclass(frozen=True)
class Profile:
    width: int
    height: int
    ground_y: int
    cube_px: float
    cube_hue: float
    hue_tolerance: float = 25
    saturation_min: int = 110
    value_min: int = 80
    spike_saturation_max: int = 145
    spike_value_min: int = 175
    player_left_fraction: float = 0.2
    player_right_fraction: float = 0.55
    schema_version: int = 1

    def __post_init__(self):
        values = asdict(self)
        if not all(isinstance(v, (int, float)) and not isinstance(v, bool) and np.isfinite(v) for v in values.values()):
            raise ValueError("Profile values must be finite numbers")
        if self.schema_version != 1 or not all(isinstance(v, int) for v in (self.width, self.height, self.ground_y)):
            raise ValueError("Invalid profile version or image dimensions")
        if not (200 <= self.width <= 10000 and 150 <= self.height <= 10000 and 20 <= self.ground_y < self.height):
            raise ValueError("Profile dimensions or ground line are out of bounds")
        if not (15 <= self.cube_px <= min(self.width, self.height) / 3 and 0 <= self.cube_hue < 180 and 0 < self.hue_tolerance < 90):
            raise ValueError("Invalid cube size or hue calibration")
        if not (0 <= self.player_left_fraction < self.player_right_fraction <= 1):
            raise ValueError("Invalid player search area")
        for key in ("saturation_min", "value_min", "spike_saturation_max", "spike_value_min"):
            if not 0 <= values[key] <= 255:
                raise ValueError(f"Invalid {key}")

    @property
    def scale(self):
        # One normal cube corresponds to DashEnv.player_size, not one unit.
        return self.cube_px / 0.8

    @classmethod
    def load(cls, path):
        try:
            return cls(**json.loads(Path(path).read_text(encoding="utf-8")))
        except TypeError as exc:
            raise ValueError("Unsupported or incomplete screen profile") from exc

    def save(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2) + "\n", encoding="utf-8")

    @classmethod
    def from_selection(cls, frame, cube, ground_y):
        x, y, w, h = map(int, cube)
        if not (0 <= x < x+w <= frame.shape[1] and 0 <= y < y+h <= frame.shape[0] and min(w, h) >= 15):
            raise ValueError("Select the whole grounded cube, including its outline")
        if abs(w-h) > max(w,h)*0.2 or abs(y+h-ground_y) > max(w,h)*0.15:
            raise ValueError("Calibration needs an upright cube standing on the selected ground")
        hsv = cv2.cvtColor(frame[y:y+h, x:x+w], cv2.COLOR_RGB2HSV)
        pixels = hsv[(hsv[:,:,1] >= 110) & (hsv[:,:,2] >= 100)]
        if len(pixels) < w*h*0.1:
            raise ValueError("Cube needs a distinct saturated colour for this detector")
        counts, edges = np.histogram(pixels[:,0], bins=36, range=(0,180))
        hue = float(edges[int(np.argmax(counts))] + 2.5)
        return cls(frame.shape[1], frame.shape[0], int(ground_y), (w+h)/2, hue)


@dataclass
class Scene:
    cube: Box
    spikes: tuple[Box, ...]
    ground_y: int
    height: float
    vy: float
    speed: float
    moving: bool
    grounded: bool
    ready: bool
    observation: np.ndarray


def _components(mask):
    count, _, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8))
    return [Box(int(x), int(y), int(x+w), int(y+h)) for x,y,w,h,area in stats[1:count] if area >= 12]


class Observer:
    def __init__(self, profile):
        self.profile = profile
        self.reset()

    def reset(self):
        self.previous = None
        self.previous_time = None
        self.speed = 0.0
        self.last_motion = -float("inf")
        self.frames = 0
        self.motion_patch = None

    def observe(self, frame, stamp):
        p = self.profile
        if frame.shape != (p.height, p.width, 3) or frame.dtype != np.uint8:
            raise PerceptionError("Window size changed; recalibrate before controlling")
        if not np.isfinite(stamp) or (self.previous_time is not None and stamp <= self.previous_time):
            raise PerceptionError("Frame timestamps must increase")
        hsv = cv2.cvtColor(frame, cv2.COLOR_RGB2HSV)
        bright = (hsv[:,:,1] <= p.spike_saturation_max) & (hsv[:,:,2] >= p.spike_value_min)
        # The known flat ground line must still be visible (menus dim/hide it).
        rows = bright[max(0,p.ground_y-3):p.ground_y+4]
        if not len(rows) or rows.sum(axis=1).max() < p.width*0.25:
            raise PerceptionError("Ground line missing: menu, occlusion, camera change or unsupported level")
        hue_diff = np.abs(hsv[:,:,0].astype(float)-p.cube_hue)
        hue_diff = np.minimum(hue_diff, 180-hue_diff)
        colour = (hue_diff <= p.hue_tolerance) & (hsv[:,:,1] >= p.saturation_min) & (hsv[:,:,2] >= p.value_min)
        colour[:max(0,int(p.ground_y-4*p.cube_px))] = False
        colour[p.ground_y+3:] = False
        colour[:,:int(p.width*p.player_left_fraction)] = False
        colour[:,int(p.width*p.player_right_fraction):] = False
        colour = cv2.morphologyEx(colour.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((5,5),np.uint8))
        candidates = [b for b in _components(colour)
                      if 0.65*p.cube_px <= b.width <= 1.5*p.cube_px
                      and 0.65*p.cube_px <= b.height <= 1.5*p.cube_px
                      and 0.7 < b.width/b.height < 1.4
                      and colour[b.top:b.bottom,b.left:b.right].sum() >= p.cube_px**2*0.18]
        if len(candidates) != 1:
            raise PerceptionError(f"Expected one cube; detected {len(candidates)}. Control stopped")
        colour_box = candidates[0]
        cx = (colour_box.left+colour_box.right)/2
        cy = (colour_box.top+colour_box.bottom)/2
        # Use the calibrated physical square, not the rotating visual AABB.
        half = p.cube_px/2
        cube = Box(round(cx-half), round(cy-half), round(cx+half), round(cy+half))
        y = max(0.0, (p.ground_y-(cy+half))/p.scale)
        grounded = y <= 2/p.scale
        if grounded:
            y = 0.0

        hazards = bright.copy().astype(np.uint8)
        top = max(0,int(p.ground_y-3*p.cube_px))
        hazards[:top] = 0
        hazards[max(0,p.ground_y-5):] = 0  # separate outlines from the ground line
        hazards[:,:max(0,cube.left-3)] = 0
        contours, _ = cv2.findContours(hazards, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        spikes = []
        for contour in contours:
            x0,y0,w,h = cv2.boundingRect(contour)
            if h < p.cube_px*0.45 or w < p.cube_px*0.3:
                continue
            if y0+h < p.ground_y-0.2*p.cube_px:
                continue
            hull = cv2.convexHull(contour)
            fill = cv2.contourArea(hull)/max(1,w*h)
            if (p.cube_px*0.6 <= w <= p.cube_px*1.3 and
                    p.cube_px*0.6 <= h <= p.cube_px*1.2 and 0.35 <= fill <= 0.72):
                spikes.append(Box(x0,y0,x0+w,p.ground_y))
            elif x0 > cube.right and h > p.cube_px*0.5:
                raise PerceptionError("Unsupported block/platform or ambiguous obstacle ahead")
        spikes.sort(key=lambda b:b.left)
        groups = []
        for box in spikes:
            if groups and box.left-groups[-1].right < p.cube_px*0.12:
                a = groups.pop()
                box = Box(a.left,min(a.top,box.top),box.right,max(a.bottom,box.bottom))
            groups.append(box)

        vy = 0.0
        if self.previous is not None:
            dt = stamp-self.previous_time
            if dt > 0.25:
                raise PerceptionError("Frame gap exceeds 250 ms; re-arm on fresh frames")
            vy = (y-self.previous.height)/dt
            shifts = []
            old_cx = (self.previous.cube.left+self.previous.cube.right)/2
            for old in self.previous.spikes:
                matches = [b for b in groups if abs(old.width-b.width) < p.cube_px*0.15
                           and -3 <= old.left-b.left <= p.scale*20*dt+3]
                if matches:
                    new = min(matches,key=lambda b:abs(old.left-b.left))
                    shifts.append((old.left-new.left+cx-old_cx)/p.scale/dt)
            if shifts:
                measured = float(np.median(shifts))
                if 0.5 < measured < 20:
                    self.speed = measured if self.speed == 0 else self.speed*0.65+measured*0.35
                    self.last_motion = stamp
            if abs(cx-old_cx) > p.cube_px*1.5:
                raise PerceptionError("Cube teleported: likely restart or wrong detection")
        if grounded:
            vy = 0.0
        # Background movement proves frames are still advancing between spikes.
        # It never supplies speed: retain the last speed measured from hazards.
        patch = cv2.resize(frame[max(0,int(p.ground_y-3*p.cube_px)):max(1,int(p.ground_y-1.4*p.cube_px)),
                                 int(p.width*0.6):],(100,30)).astype(np.int16)
        if self.motion_patch is not None and self.speed > 0:
            difference = np.abs(patch-self.motion_patch)
            if difference.mean() > 1 and np.mean(difference > 5) > 0.02:
                self.last_motion = stamp
        self.motion_patch = patch
        moving = stamp-self.last_motion < 0.35
        obs = np.zeros(16,dtype=np.float32)
        obs[:4] = (y/3, vy/12, float(grounded), self.speed/10)
        for i,box in enumerate([b for b in groups if b.right>cube.left][:3]):
            distance = (box.left-cube.right)/p.scale
            if distance <= 16:
                obs[4+4*i:8+4*i] = (distance/16,box.width/p.scale/3,box.height/p.scale/2,1)
        self.frames += 1
        scene = Scene(cube,tuple(groups),p.ground_y,y,vy,self.speed,moving,grounded,
                      self.frames>=3 and moving,np.clip(obs,-1,1))
        self.previous, self.previous_time = scene, stamp
        return scene


def annotate(frame, scene=None, status="PREVIEW - no keyboard input"):
    result = frame.copy()
    if scene:
        for box in (scene.cube,*scene.spikes):
            cv2.rectangle(result,(box.left,box.top),(box.right,box.bottom),(255,214,70),2)
        cv2.line(result,(0,scene.ground_y),(result.shape[1],scene.ground_y),(60,255,150),2)
        cv2.putText(result,f"v={scene.speed:.2f}  y={scene.height:.2f}  vy={scene.vy:.2f}  ready={scene.ready}",
                    (20,result.shape[0]-35),cv2.FONT_HERSHEY_SIMPLEX,0.65,(255,255,255),2)
    cv2.rectangle(result,(0,0),(result.shape[1],45),(15,20,28),-1)
    cv2.putText(result,status[:130],(15,29),cv2.FONT_HERSHEY_SIMPLEX,0.6,(255,220,100),2)
    return result
