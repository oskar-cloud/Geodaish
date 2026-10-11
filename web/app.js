import { number, percent, compact, decimal, duration, runProgress, connectionState, looksLikeSnapshot } from './data-model.js';
import { ReplayPlayer } from './replay.js';

const $ = selector => document.querySelector(selector);
const text = (selector, value) => { $(selector).textContent = value; };
const escape = value => String(value).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
const state = { data: null, demo: null, live: null, source: 'demo', metric: 'meanProgress', error: false, apiReason: null, busy: false };
const player = new ReplayPlayer($('#game'));
let plot = null;

function navigate() {
  const view = ['overview', 'evaluation', 'connect'].includes(location.hash.slice(1)) ? location.hash.slice(1) : 'overview';
  const labels = { overview: 'Översikt', evaluation: 'Utvärdering', connect: 'Koppla träningen' };
  document.querySelectorAll('.view').forEach(el => { el.hidden = el.id !== `view-${view}`; });
  document.querySelectorAll('[data-view]').forEach(el => {
    const active = el.dataset.view === view;
    el.classList.toggle('active', active);
    active ? el.setAttribute('aria-current', 'page') : el.removeAttribute('aria-current');
  });
  text('#page-name', labels[view]);
  $('#page-title').innerHTML = { overview: 'Se din AI lära sig<span>.</span>', evaluation: 'Resultat, på riktigt<span>.</span>', connect: 'Ta träningen online<span>.</span>' }[view];
  text('#page-description', { overview: 'Från första hoppet till en hel bana. Följ varje framsteg.', evaluation: 'Validering under träningen. Ett separat test efteråt.', connect: 'Samma labb. Tillgängligt var du än är.' }[view]);
}
window.addEventListener('hashchange', navigate); navigate();

function updateStatus() {
  if (!state.data) return;
  const status = connectionState(state.data, state.source, Date.now(), state.error);
  const pill = $('#status-pill');
  pill.className = `status-pill ${status.kind}`;
  pill.innerHTML = `<i></i>${status.label}`;
  const stamp = new Date(state.data.telemetry.updatedAt);
  text('#sync-state', status.age === null ? 'Sparade mätvärden' : `Rapport ${duration(status.age)} sedan`);
  let notice;
  if (state.source === 'demo') {
    notice = 'Sparade resultat från en verklig träningskörning. Koppla träningen för att följa nya pass live.';
    if (state.apiReason === 'storage_unavailable') notice += ' Livelagringen svarar inte just nu.';
  } else if (state.error) notice = 'Kontakten med servern saknas. Senaste mottagna data visas; inga nya värden uppskattas.';
  else if (status.kind === 'stale' && state.data.run.status === 'running') notice = 'Inga nya rapporter har kommit på över 20 sekunder. Macen kan vara pausad, offline eller upptagen med validering.';
  else if (state.data.run.status === 'running') notice = 'Live från Python-träningen. Statistik uppdateras ungefär var femte sekund; uppspelningen visar senaste valideringen.';
  else notice = `Träningspasset ${state.data.run.status === 'completed' ? 'avslutades' : state.data.run.status === 'interrupted' ? 'avbröts' : 'stoppades'} ${stamp.toLocaleString('sv-SE')}. De sista rapporterade resultaten visas.`;
  text('#source-notice', notice);
  $('#source-notice').classList.toggle('error', status.kind === 'stale');
}

function spark(selector, history, key) {
  if (!history.length) { $(selector).innerHTML = ''; return; }
  const min = history[0].step, range = Math.max(1, history.at(-1).step - min);
  const points = history.map(p => `${((p.step - min) / range * 72).toFixed(1)},${(29 - p[key] * 25).toFixed(1)}`).join(' ');
  $(selector).innerHTML = `<svg viewBox="0 0 74 32" aria-hidden="true"><polyline points="${points}" fill="none" stroke-width="1.5"/></svg>`;
}

function render(data, source) {
  if (!looksLikeSnapshot(data)) return;
  const differentRun = state.data?.run.id !== data.run.id;
  state.data = data; state.source = source;
  $('#fatal-error').hidden = true;
  const last = data.history.at(-1), t = data.telemetry, r = data.run, progress = runProgress(data);
  text('#run-name', r.label);
  const environment = r.environment;
  const mode = environment ? ` · ${environment.observations === 'pixels' ? 'Bildtolkning' : 'Speldata'} · ${environment.level === 'test' ? 'Fast testbana' : 'Genererade banor'} · ${environment.input_delay} bildrutor fördröjning` : '';
  text('#run-detail', `${r.algorithm} · ${r.numEnvs} miljöer · seed ${r.seed}${mode}`);
  text('#metric-win', last ? percent(last.successRate) : '—');
  text('#metric-win-note', last ? `${number(Math.round(last.successRate * last.episodes))} av ${last.episodes} ${environment?.level === 'test' ? 'försök på samma testbana' : 'valideringsbanor'}` : 'Inväntar validering');
  text('#metric-progress', last ? percent(last.meanProgress) : '—');
  text('#metric-steps', compact(t.step));
  text('#metric-steps-note', `${number(t.step)} av ${number(r.targetSteps)}`);
  text('#metric-speed', t.stepsPerSecond > 0 ? number(t.stepsPerSecond) : '—');
  $('#training-progress').style.width = `${progress * 100}%`;
  spark('#spark-win', data.history, 'successRate'); spark('#spark-progress', data.history, 'meanProgress');
  text('#run-percent', percent(progress)); $('#run-progress-fill').style.width = `${progress * 100}%`;
  text('#run-step-detail', `${number(t.step - r.initialSteps)} av ${number(r.targetSteps - r.initialSteps)} nya steg`);
  text('#run-difficulty', { easy: 'Lätt', normal: 'Normal', hard: 'Svår' }[r.difficulty]);
  text('#run-envs', r.numEnvs); text('#run-episodes', t.episodes === null ? 'Ej registrerat' : number(t.episodes));
  text('#run-duration', duration(t.elapsedSeconds)); text('#run-seed', r.seed);
  text('#run-insight', r.initialSteps > 0 ? `Återupptagen från ${number(r.initialSteps)} steg. Framstegen ovan gäller detta träningspass.` : 'Agenten börjar från noll. Kurvorna visar hur den klarar banor som används för validering.');
  if (differentRun || $('#follow-model').checked || !player.replay) player.setReplay(data.replay, `${r.id}/${data.replay?.id || 'empty'}`);
  renderChart(); renderMilestones(); renderEvaluation(); updateStatus();
}

function renderChart() {
  if (!state.data) return;
  const points = state.data.history, metric = state.metric;
  text('#chart-samples', `${points.length} mätpunkter`);
  text('#chart-legend-label', { meanProgress: 'Genomsnittligt framsteg', successRate: 'Andel klarade banor', meanReward: 'Genomsnittlig belöning' }[metric]);
  $('#chart-empty').hidden = points.length > 0;
  const svg = $('#learning-chart'), W = 720, H = 220, left = 45, right = 17, top = 16, bottom = 31;
  const lo = state.data.run.initialSteps, hi = Math.max(lo + 1, points.at(-1)?.step || state.data.run.targetSteps);
  const values = points.map(p => p[metric]);
  const yMin = metric === 'meanReward' ? Math.floor(Math.min(0, ...values) / 5) * 5 : 0;
  const yMax = metric === 'meanReward' ? Math.max(yMin + 5, Math.ceil(Math.max(1, ...values) / 5) * 5) : 1;
  const x = value => left + (value - lo) / (hi - lo) * (W - left - right);
  const y = value => top + (1 - (value - yMin) / (yMax - yMin)) * (H - top - bottom);
  let html = '<title>Validering över kumulativa träningssteg. Alla värden finns även i tabellen under Utvärdering.</title><defs><linearGradient id="area" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="#b3ed89" stop-opacity=".16"/><stop offset="100%" stop-color="#b3ed89" stop-opacity=".005"/></linearGradient></defs>';
  for (let i = 0; i <= 4; i++) {
    const value = yMin + (yMax - yMin) * i / 4, py = y(value);
    html += `<line x1="${left}" y1="${py}" x2="${W - right}" y2="${py}" stroke="#313d34" stroke-width=".6" stroke-dasharray="3 5"/><text x="${left - 9}" y="${py + 3}" text-anchor="end" fill="#7f9185" stroke="none" font-size="9" font-family="DM Sans, sans-serif">${metric === 'meanReward' ? decimal(value) : percent(value)}</text>`;
  }
  for (let i = 0; i <= 5; i++) {
    const value = lo + (hi - lo) * i / 5;
    html += `<text x="${x(value)}" y="${H - 7}" text-anchor="${i === 0 ? 'start' : i === 5 ? 'end' : 'middle'}" fill="#7f9185" stroke="none" font-size="9" font-family="DM Sans, sans-serif">${compact(value)}</text>`;
  }
  if (points.length) {
    const coords = points.map(p => `${x(p.step)},${y(p[metric])}`).join(' ');
    html += `<polygon points="${x(points[0].step)},${y(yMin)} ${coords} ${x(points.at(-1).step)},${y(yMin)}" fill="url(#area)" stroke="none"/><polyline points="${coords}" stroke="#b3ed89" stroke-width="2" fill="none"/>`;
    for (const p of points) html += `<circle cx="${x(p.step)}" cy="${y(p[metric])}" r="2" fill="#c2ed9d" stroke="#17211a" stroke-width="1"/>`;
  }
  html += `<line id="hover-line" y1="${top}" y2="${H - bottom}" stroke="#c1d6ac" stroke-dasharray="3 3" visibility="hidden"/><circle id="hover-dot" r="4" fill="#d0f4a5" stroke="#284127" stroke-width="2" visibility="hidden"/>`;
  svg.innerHTML = html;
  plot = { points, x, y };
}
$('#learning-chart').addEventListener('pointermove', event => {
  if (!plot?.points.length) return;
  const svg = $('#learning-chart'), coord = svg.createSVGPoint();
  coord.x = event.clientX; coord.y = event.clientY;
  const local = coord.matrixTransform(svg.getScreenCTM().inverse());
  const point = plot.points.reduce((best, p) => Math.abs(plot.x(p.step) - local.x) < Math.abs(plot.x(best.step) - local.x) ? p : best);
  const cx = plot.x(point.step), cy = plot.y(point[state.metric]);
  $('#hover-line').setAttribute('x1', cx); $('#hover-line').setAttribute('x2', cx); $('#hover-line').setAttribute('visibility', 'visible');
  $('#hover-dot').setAttribute('cx', cx); $('#hover-dot').setAttribute('cy', cy); $('#hover-dot').setAttribute('visibility', 'visible');
  const tooltip = $('#chart-tooltip'), rect = $('#chart-container').getBoundingClientRect();
  tooltip.innerHTML = `${state.metric === 'meanReward' ? decimal(point[state.metric]) : percent(point[state.metric])}<small>${number(point.step)} steg · ${point.episodes} banor</small>`;
  tooltip.style.left = `${Math.max(85, Math.min(rect.width - 85, event.clientX - rect.left))}px`;
  tooltip.style.top = `${Math.max(54, event.clientY - rect.top - 12)}px`; tooltip.hidden = false;
});
$('#learning-chart').addEventListener('pointerleave', () => {
  $('#chart-tooltip').hidden = true;
  $('#hover-line')?.setAttribute('visibility', 'hidden'); $('#hover-dot')?.setAttribute('visibility', 'hidden');
});
document.querySelectorAll('[data-metric]').forEach(button => button.onclick = () => {
  state.metric = button.dataset.metric;
  document.querySelectorAll('[data-metric]').forEach(el => { el.classList.toggle('selected', el === button); el.setAttribute('aria-pressed', String(el === button)); });
  renderChart();
});

function renderMilestones() {
  const h = state.data.history, items = [];
  if (h.length) items.push(['Första mätpunkten', `${compact(h[0].step)} steg · ${percent(h[0].meanProgress)} av banan`]);
  const won = h.find(p => p.successRate > 0);
  if (won) items.push(['Första klarade banan', `${compact(won.step)} steg · ${percent(won.successRate)} klarade`]);
  const full = h.find(p => p.successRate === 1);
  if (full) items.push(['Alla valideringsbanor klarade', `${compact(full.step)} steg · ${full.episodes} av ${full.episodes} banor`]);
  if (!items.length) items.push(['Träningspasset har startat', 'Inväntar första valideringen']);
  if (items.length < 3 && h.length > 1) items.push(['Senaste mätpunkten', `${compact(h.at(-1).step)} steg · ${percent(h.at(-1).meanProgress)} av banan`]);
  $('#milestones').innerHTML = items.map(([label, detail]) => `<li>${escape(label)}<small>${escape(detail)}</small></li>`).join('');
}

function renderEvaluation() {
  const test = state.data.test;
  if (test?.policies?.length) {
    const policies = [...test.policies].sort((a, b) => Number(b.label.includes('PPO')) - Number(a.label.includes('PPO')));
    $('#test-cards').innerHTML = policies.map(p => `<article class="test-card"><h3>${escape(p.label.includes('PPO') ? 'Tränad PPO-agent' : p.label === 'random' ? 'Slumpmässiga hopp' : 'Handkodad referens')}</h3><strong>${percent(p.successRate)}</strong><p>${Math.round(p.successRate * p.episodes)} av ${p.episodes} banor klarade<br>${percent(p.meanProgress)} genomsnittligt framsteg</p></article>`).join('');
    text('#test-note', `${policies[0].episodes} separata testbanor, seeds ${policies[0].firstSeed}–${policies[0].firstSeed + policies[0].episodes - 1}. Testet gäller den sparade demomodellen i simulatorn. Den handkodade referensen är inte en tränad AI.`);
  } else {
    $('#test-cards').innerHTML = '<p class="small-note">Inget separat sluttest är bifogat för detta träningspass.</p>';
    text('#test-note', 'Valideringen nedan används under träningen. Kör geodaish evaluate efter modellvalet för att mäta prestanda på separata testbanor.');
  }
  $('#validation-table').innerHTML = [...state.data.history].reverse().map(p => `<tr><td>${number(p.step)}</td><td>${percent(p.successRate)}</td><td>${percent(p.meanProgress)}</td><td>${decimal(p.meanReward)}</td><td>${p.episodes}</td></tr>`).join('') || '<tr><td colspan="5">Väntar på första valideringen.</td></tr>';
}

async function fetchJson(url) {
  const response = await fetch(url, { cache: 'no-store', signal: AbortSignal.timeout(7000) });
  const data = await response.json();
  if (!response.ok) throw Object.assign(new Error(data.error || `HTTP ${response.status}`), { reason: data.error });
  if (!looksLikeSnapshot(data)) throw new Error('Invalid report');
  return data;
}

async function refresh() {
  if (state.busy || document.hidden || $('#source-select').value === 'demo') return;
  state.busy = true;
  try {
    const data = await fetchJson('/api/training');
    state.live = data; state.error = false; state.apiReason = null;
    if ($('#source-select').value === 'auto') render(data, 'live');
  } catch (error) {
    state.apiReason = error.reason;
    state.error = state.source === 'live';
    if (!state.data && state.demo) render(state.demo, 'demo');
    updateStatus();
  } finally { state.busy = false; }
}

async function boot() {
  $('#retry').disabled = true;
  try {
    state.demo = await fetchJson('/data/demo.json');
    if (state.source !== 'live') render(state.demo, 'demo');
  } catch { /* The live endpoint may still be available. */ }
  await refresh();
  $('#fatal-error').hidden = !!state.data;
  $('#retry').disabled = false;
}
$('#retry').onclick = boot;
$('#source-select').onchange = () => {
  state.error = false;
  if ($('#source-select').value === 'demo' && state.demo) render(state.demo, 'demo');
  else { if (state.live) render(state.live, 'live'); refresh(); }
};
$('#follow-model').onchange = () => { if ($('#follow-model').checked && state.data) player.setReplay(state.data.replay, `${state.data.run.id}/${state.data.replay?.id || 'empty'}`); };
setInterval(refresh, 5000); setInterval(updateStatus, 1000);
document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });

function download(content, type, name) {
  const url = URL.createObjectURL(new Blob([content], { type })), link = document.createElement('a');
  link.href = url; link.download = name; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
}
$('#download-report').onclick = () => { if (state.data) download(JSON.stringify(state.data, null, 2), 'application/json', 'geodaish-report.json'); };
$('#download-table').onclick = () => {
  if (!state.data) return;
  download('step,success_rate,mean_progress,mean_reward,episodes\n' + state.data.history.map(p => [p.step, p.successRate, p.meanProgress, p.meanReward, p.episodes].join(',')).join('\n'), 'text/csv', 'geodaish-validation.csv');
};
const site = ['localhost', '127.0.0.1'].includes(location.hostname) ? 'https://ditt-projekt.vercel.app' : location.origin;
text('#training-command', `export GEODAISH_DASHBOARD_URL="${site}"\nread -s GEODAISH_DASHBOARD_TOKEN\nexport GEODAISH_DASHBOARD_TOKEN\ngeodaish train --steps 2000000`);
$('#copy-command').onclick = async () => {
  try {
    await navigator.clipboard.writeText($('#training-command').textContent);
    text('#toast', 'Kommando kopierat. Ange nyckeln när read väntar på inmatning.');
  } catch { text('#toast', 'Markera och kopiera kommandot manuellt.'); }
  $('#toast').hidden = false; setTimeout(() => { $('#toast').hidden = true; }, 4000);
};

boot();
