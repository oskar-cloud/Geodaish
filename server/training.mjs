import { createHash, timingSafeEqual } from 'node:crypto';

export const MAX_BYTES = 512 * 1024;
const KEY = 'geodaish:training:latest';
const finite = value => typeof value === 'number' && Number.isFinite(value);
const nonnegative = value => finite(value) && value >= 0;
const fraction = value => finite(value) && value >= 0 && value <= 1;
const short = value => typeof value === 'string' && value.length > 0 && value.length <= 160;
const date = value => typeof value === 'string' && Number.isFinite(Date.parse(value));

export function validateSnapshot(data) {
  const r = data?.run, t = data?.telemetry;
  if (data?.schemaVersion !== 1 || !r || !t) throw new Error('Unsupported snapshot');
  if (!short(r.id) || !short(r.label) || !date(r.startedAt) ||
      !['running', 'completed', 'interrupted', 'failed', 'imported'].includes(r.status) ||
      !['easy', 'normal', 'hard'].includes(r.difficulty) || r.algorithm !== 'PPO' ||
      ![r.seed, r.numEnvs, r.initialSteps, r.targetSteps].every(nonnegative)) {
    throw new Error('Invalid run');
  }
  if (![t.step, t.elapsedSeconds, t.stepsPerSecond, t.sequence].every(nonnegative) ||
      !date(t.updatedAt) || !(t.episodes === null || nonnegative(t.episodes)) ||
      !(t.meanEpisodeReward === null || finite(t.meanEpisodeReward)) ||
      !(t.meanEpisodeLength === null || nonnegative(t.meanEpisodeLength))) {
    throw new Error('Invalid telemetry');
  }
  if (!Array.isArray(data.history) || data.history.length > 1000) throw new Error('Invalid history');
  let last = -1;
  for (const p of data.history) {
    if (!nonnegative(p.step) || p.step < last || !fraction(p.successRate) ||
        !fraction(p.meanProgress) || !finite(p.meanReward) || !nonnegative(p.episodes) ||
        !(p.elapsedSeconds === null || nonnegative(p.elapsedSeconds))) throw new Error('Invalid point');
    last = p.step;
  }
  if (data.replay !== null) {
    const p = data.replay;
    if (!p || !short(p.id) || !short(p.modelLabel) || !nonnegative(p.modelStep) ||
        !nonnegative(p.seed) || p.fps !== 60 || !finite(p.length) || p.length <= 0 ||
        !finite(p.playerSize) || p.playerSize <= 0 || !nonnegative(p.speed) ||
        !Array.isArray(p.frames) || p.frames.length < 2 || p.frames.length > 2000 ||
        !Array.isArray(p.obstacles) || p.obstacles.length > 100) throw new Error('Invalid replay');
    for (const f of p.frames) {
      if (!Array.isArray(f) || f.length !== 4 || !f.every(nonnegative) ||
          ![0, 1].includes(f[2])) throw new Error('Invalid frame');
    }
    for (const o of p.obstacles) {
      if (![o.x, o.height].every(nonnegative) || !Number.isInteger(o.count) ||
          o.count < 1 || o.count > 3) throw new Error('Invalid obstacle');
    }
    if (!p.result || typeof p.result.success !== 'boolean' || typeof p.result.dead !== 'boolean' ||
        !fraction(p.result.progress) || !finite(p.result.reward) ||
        !nonnegative(p.result.jumps)) throw new Error('Invalid replay result');
  }
  // Live uploads never accept arbitrary configuration, filesystem paths, or credentials.
  return {
    schemaVersion: 1,
    run: Object.fromEntries(['id', 'label', 'status', 'algorithm', 'difficulty', 'seed',
      'numEnvs', 'initialSteps', 'targetSteps', 'startedAt'].map(k => [k, r[k]])),
    telemetry: Object.fromEntries(['step', 'elapsedSeconds', 'stepsPerSecond', 'sequence',
      'updatedAt', 'episodes', 'meanEpisodeReward', 'meanEpisodeLength'].map(k => [k, t[k]])),
    history: data.history.map(p => Object.fromEntries(['step', 'elapsedSeconds', 'successRate',
      'meanProgress', 'meanReward', 'episodes'].map(k => [k, p[k]]))),
    replay: data.replay === null ? null : {
      ...Object.fromEntries(['id', 'modelLabel', 'modelStep', 'seed', 'fps', 'length',
        'playerSize', 'speed'].map(k => [k, data.replay[k]])),
      frames: data.replay.frames,
      obstacles: data.replay.obstacles.map(o => ({ x: o.x, count: o.count, height: o.height })),
      result: Object.fromEntries(['success', 'dead', 'progress', 'reward', 'jumps'].map(k => [k, data.replay.result[k]])),
    },
    test: null,
  };
}

function authorized(header, token) {
  if (!token || token.length < 32 || typeof header !== 'string') return false;
  const hash = value => createHash('sha256').update(value).digest();
  return timingSafeEqual(hash(header), hash(`Bearer ${token}`));
}

// Reject delayed packets, including packets from an older run after a newer one starts.
export const STORE_SCRIPT = `
local old = redis.call('GET', KEYS[1])
if old then
  local a = cjson.decode(old)
  local b = cjson.decode(ARGV[1])
  if a.run.startedAt > b.run.startedAt then return 0 end
  if a.run.id == b.run.id then
    if a.telemetry.sequence > b.telemetry.sequence then return 0 end
    if a.telemetry.sequence == b.telemetry.sequence then return 1 end
  end
end
redis.call('SET', KEYS[1], ARGV[1])
return 1`;

export async function handleTraining({ method, authorization, body, env = process.env, fetcher = fetch }) {
  const response = (status, data) => ({ status, body: data });
  if (!['GET', 'POST'].includes(method)) return response(405, { error: 'method_not_allowed' });
  if (method === 'POST' && !authorized(authorization, env.TRAINING_API_TOKEN)) {
    return response(401, { error: 'unauthorized' });
  }
  const url = env.UPSTASH_REDIS_REST_URL || env.KV_REST_API_URL;
  const token = env.UPSTASH_REDIS_REST_TOKEN || env.KV_REST_API_TOKEN;
  if (!url || !token) return response(503, { error: 'live_not_configured' });
  let snapshot;
  if (method === 'POST') {
    if (Buffer.byteLength(body || '') > MAX_BYTES) return response(413, { error: 'snapshot_too_large' });
    try {
      snapshot = validateSnapshot(JSON.parse(body));
    } catch {
      return response(400, { error: 'invalid_snapshot' });
    }
    snapshot.receivedAt = new Date().toISOString();
  }
  try {
    const command = method === 'GET' ? ['GET', KEY] : ['EVAL', STORE_SCRIPT, 1, KEY, JSON.stringify(snapshot)];
    const result = await fetcher(url, {
      method: 'POST', headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      body: JSON.stringify(command), signal: AbortSignal.timeout(7000),
    });
    if (!result.ok) throw new Error('Storage request failed');
    const payload = await result.json();
    if (payload.error || !Object.hasOwn(payload, 'result')) throw new Error('Storage command failed');
    if (method === 'POST') return response(payload.result === 1 ? 200 : 409,
      payload.result === 1 ? { ok: true } : { error: 'stale_snapshot' });
    if (payload.result === null) return response(404, { error: 'no_training_yet' });
    const stored = JSON.parse(payload.result);
    return response(200, { ...validateSnapshot(stored), receivedAt: stored.receivedAt });
  } catch {
    return response(502, { error: 'storage_unavailable' });
  }
}
