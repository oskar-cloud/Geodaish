export const number = value => new Intl.NumberFormat('sv-SE', { maximumFractionDigits: 0 }).format(value);
export const percent = value => new Intl.NumberFormat('sv-SE', { style: 'percent', maximumFractionDigits: 0 }).format(value);
export const compact = value => new Intl.NumberFormat('sv-SE', { notation: 'compact', maximumFractionDigits: 2 }).format(value);
export const decimal = value => new Intl.NumberFormat('sv-SE', { maximumFractionDigits: 2 }).format(value);
export function duration(value) {
  const seconds = Math.max(0, Math.floor(value));
  return seconds < 60 ? `${seconds} s` : `${Math.floor(seconds / 60)} min ${seconds % 60} s`;
}
export function runProgress(data) {
  const total = data.run.targetSteps - data.run.initialSteps;
  return total > 0 ? Math.min(1, Math.max(0, (data.telemetry.step - data.run.initialSteps) / total)) : 0;
}
export function connectionState(data, source, now = Date.now(), error = false) {
  if (source === 'demo') return { label: 'SPARAD KÖRNING', kind: 'saved', age: null };
  const stamp = Date.parse(data.receivedAt || data.telemetry.updatedAt);
  const age = Math.max(0, (now - stamp) / 1000);
  if (error) return { label: 'KONTAKT SAKNAS', kind: 'stale', age };
  if (data.run.status === 'running') return age > 20
    ? { label: 'INGA NYA DATA', kind: 'stale', age }
    : { label: 'TRÄNAR LIVE', kind: 'live', age };
  return { label: { completed: 'KLAR', interrupted: 'AVBRUTEN', failed: 'TRÄNINGSFEL', imported: 'SPARAD KÖRNING' }[data.run.status] || 'SPARAD',
    kind: ['failed', 'interrupted'].includes(data.run.status) ? 'stale' : 'saved', age };
}
export function looksLikeSnapshot(data) {
  return data?.schemaVersion === 1 && data.run && data.telemetry && Array.isArray(data.history)
    && Number.isFinite(data.telemetry.step) && typeof data.run.label === 'string';
}
