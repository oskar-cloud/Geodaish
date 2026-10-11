import { handleSnapshot } from './training.mjs';

const number = v => typeof v === 'number' && Number.isFinite(v);
const nonnegative = v => number(v) && v >= 0;
const short = v => typeof v === 'string' && v.length <= 160;
const date = v => typeof v === 'string' && Number.isFinite(Date.parse(v));
const pick = (o, keys) => Object.fromEntries(keys.map(k => [k, o[k]]));

export function validateWindows(data) {
  const r = data?.run, t = data?.telemetry, s = data?.scene;
  if (data?.schemaVersion !== 1 || data.source !== 'geometry-dash-windows' || !r || !t ||
      !short(r.id) || !r.id || !short(r.label) || !date(r.startedAt) ||
      !['running', 'stopped'].includes(r.status) || !['preview', 'probe', 'run'].includes(r.mode) ||
      !['space','up'].includes(r.jumpKey) ||
      !(r.model === null || short(r.model))) throw new Error('Invalid Windows run');
  if (![t.sequence,t.elapsedSeconds,t.frames,t.validFrames,t.presses].every(nonnegative) ||
      !date(t.updatedAt) || ![true,false].includes(t.armed) || ![true,false].includes(t.held) ||
      ![null,0,1].includes(t.action) || ![t.captureMs,t.pipelineMs].every(v => v === null || nonnegative(v)) ||
      !short(t.reason)) throw new Error('Invalid Windows telemetry');
  if (t.waitingForRetry !== undefined && typeof t.waitingForRetry !== 'boolean') throw new Error('Invalid retry state');
  let scene = null;
  if (s !== null) {
    if (!s || ![s.width,s.height,s.groundY].every(nonnegative) || s.width < 200 || s.width > 10000 ||
        s.height < 150 || s.height > 10000 || s.groundY > s.height || ![true,false].includes(s.ready) ||
        !Array.isArray(s.spikes) || s.spikes.length > 20 || !Array.isArray(s.observation) ||
        s.observation.length !== 16 || !s.observation.every(v => number(v) && v >= -1 && v <= 1)) throw new Error('Invalid scene');
    const box = b => {
      if (!b || ![b.left,b.top,b.right,b.bottom].every(nonnegative) || b.left >= b.right || b.top >= b.bottom ||
          b.right > s.width || b.bottom > s.height) throw new Error('Invalid box');
      return pick(b,['left','top','right','bottom']);
    };
    scene = {...pick(s,['width','height','groundY','observation','ready']),cube:box(s.cube),spikes:s.spikes.map(box)};
  }
  if (!(data.image === null || (typeof data.image === 'string' && data.image.length < 200000 &&
      /^data:image\/jpeg;base64,[A-Za-z0-9+/]+={0,2}$/.test(data.image)))) throw new Error('Invalid image');
  return {schemaVersion:1,source:'geometry-dash-windows',
    run:pick(r,['id','label','startedAt','status','mode','model','jumpKey']),
    telemetry:{...pick(t,['sequence','updatedAt','elapsedSeconds','frames','validFrames','armed','held',
      'presses','action','captureMs','pipelineMs','reason']),waitingForRetry:t.waitingForRetry ?? false},scene,image:data.image};
}

export const handleWindows = options => handleSnapshot({...options,key:'geodaish:windows:latest',validate:validateWindows});
