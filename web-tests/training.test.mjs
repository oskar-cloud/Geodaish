import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { handleTraining, validateSnapshot, MAX_BYTES } from '../server/training.mjs';
import handler from '../api/training.js';
import { connectionState, runProgress } from '../web/data-model.js';

const demo = JSON.parse(await readFile(new URL('../web/data/demo.json', import.meta.url)));
const token = 'test-only-secret-with-at-least-32-characters';
const env = { TRAINING_API_TOKEN: token, UPSTASH_REDIS_REST_URL: 'https://example.upstash.io', UPSTASH_REDIS_REST_TOKEN: 'storage-test-token' };
const post = { method: 'POST', authorization: `Bearer ${token}`, body: JSON.stringify(demo), env };
const ok = result => ({ ok: true, json: async () => ({ result }) });

test('a real Python-exported report satisfies the API contract', () => {
  const data = validateSnapshot(demo);
  assert.ok(data.history.at(-1).successRate >= 0 && data.history.at(-1).successRate <= 1);
  assert.ok(data.replay.frames.length >= 2 && data.replay.frames.length <= 2000);
  assert.equal(data.test, null, 'a separate demo test is not attached to a live model');
  assert.equal(typeof data.replay.result.success, 'boolean');
});

test('unauthenticated upload is rejected before storage access', async () => {
  const result = await handleTraining({ ...post, authorization: 'Bearer wrong', fetcher: () => assert.fail('storage called') });
  assert.equal(result.status, 401);
});

test('no credentials fails closed for writes, and describes missing live config for reads', async () => {
  assert.equal((await handleTraining({ ...post, env: {} })).status, 401);
  assert.deepEqual(await handleTraining({ method: 'GET', env: {} }), { status: 503, body: { error: 'live_not_configured' } });
});

test('valid upload persists JSON, strips unknown fields, and can be read by another invocation', async () => {
  let stored;
  const fetcher = async (url, options) => {
    assert.equal(url, env.UPSTASH_REDIS_REST_URL);
    assert.equal(options.headers.Authorization, `Bearer ${env.UPSTASH_REDIS_REST_TOKEN}`);
    const command = JSON.parse(options.body);
    if (command[0] === 'EVAL') { stored = command.at(-1); return ok(1); }
    assert.equal(command[0], 'GET');
    return ok(stored);
  };
  const result = await handleTraining({ ...post, body: JSON.stringify({ ...demo, secret: 'must-not-be-stored' }), fetcher });
  assert.equal(result.status, 200);
  const read = await handleTraining({ method: 'GET', env, fetcher });
  assert.equal(read.status, 200);
  assert.deepEqual(read.body.history, demo.history);
  assert.equal(read.body.secret, undefined);
  assert.equal(typeof read.body.receivedAt, 'string');
});

test('malformed and oversized uploads cannot reach storage', async () => {
  const never = () => assert.fail('storage called');
  assert.equal((await handleTraining({ ...post, body: '{bad', fetcher: never })).status, 400);
  const invalid = structuredClone(demo); invalid.history[0].successRate = 1.2;
  assert.equal((await handleTraining({ ...post, body: JSON.stringify(invalid), fetcher: never })).status, 400);
  invalid.history = demo.history; invalid.replay.frames[0][2] = 17;
  assert.equal((await handleTraining({ ...post, body: JSON.stringify(invalid), fetcher: never })).status, 400);
  assert.equal((await handleTraining({ ...post, body: 'x'.repeat(MAX_BYTES + 1), fetcher: never })).status, 413);
});

test('storage rejection and failure are distinct and do not leak errors or credentials', async () => {
  assert.equal((await handleTraining({ ...post, fetcher: async () => ok(0) })).status, 409);
  const failed = await handleTraining({ ...post, fetcher: async () => { throw new Error('private-token'); } });
  assert.deepEqual(failed, { status: 502, body: { error: 'storage_unavailable' } });
  assert.equal((await handleTraining({ method: 'GET', env, fetcher: async () => ok(null) })).status, 404);
  assert.equal((await handleTraining({ method: 'DELETE', env })).status, 405);
});

test('Vercel request adapter returns JSON, disallows caching, and rejects huge bodies', async () => {
  const headers = {};
  const res = { setHeader: (key, value) => { headers[key] = value; }, status(code) { this.code = code; return this; }, json(body) { this.body = body; return this; } };
  await handler({ method: 'POST', headers: { 'content-length': MAX_BYTES + 1 } }, res);
  assert.equal(res.code, 413);
  assert.equal(headers['Cache-Control'], 'no-store');
});

test('saved results never masquerade as live training; stalled training becomes stale', () => {
  const snapshot = structuredClone(demo);
  snapshot.run.status = 'running';
  const now = Date.parse(snapshot.telemetry.updatedAt);
  assert.equal(connectionState(snapshot, 'demo', now).kind, 'saved');
  assert.equal(connectionState(snapshot, 'live', now + 5000).kind, 'live');
  assert.equal(connectionState(snapshot, 'live', now + 25000).kind, 'stale');
  assert.equal(connectionState(snapshot, 'live', now, true).label, 'KONTAKT SAKNAS');
  snapshot.run.status = 'completed';
  assert.equal(connectionState(snapshot, 'live', now + 90000).label, 'KLAR');
  assert.equal(runProgress(snapshot), 1, 'rollout rounding must not display more than 100%');
});
