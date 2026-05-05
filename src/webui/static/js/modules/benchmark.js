/**
 * modules/benchmark.js — Benchmark Suite screen logic.
 */

import { http, PATHS } from '../api.js';

const _cb = { onToast: () => {} };
export function setCallbacks(cbs) { Object.assign(_cb, cbs); }

// ── Workstation card ───────────────────────────────────────────────────────────

export async function updateWorkstationCard() {
  const badgeEl = document.getElementById('mc-bench-badge');
  const bodyEl  = document.getElementById('mc-bench-body');
  if (!bodyEl) return;

  const data    = await http.get(PATHS.benchmark.report).catch(() => null);
  const results = data?.results ?? [];

  if (!results.length) {
    if (badgeEl) { badgeEl.textContent = '—'; badgeEl.className = 'mc-badge off'; }
    bodyEl.innerHTML = '<span style="color:var(--text3)">No runs yet</span>';
    return;
  }

  const passed = results.filter(r => r.status === 'done').length;
  const pct    = Math.round((passed / results.length) * 100);

  if (badgeEl) {
    badgeEl.textContent = `${pct}%`;
    badgeEl.className   = pct === 100 ? 'mc-badge on' : 'mc-badge';
  }
  bodyEl.innerHTML = `
    <div class="mc-row"><span class="mc-key">Scenarios</span><span class="mc-val">${results.length}</span></div>
    <div class="mc-row"><span class="mc-key">Passed</span>
      <span class="mc-val" style="color:${pct===100?'#16a34a':'var(--text)'}">${passed}/${results.length}</span></div>
    <div class="mc-row"><span class="mc-key">Pass Rate</span><span class="mc-val">${pct}%</span></div>`;
}

// ── Screen init ───────────────────────────────────────────────────────────────

export async function init() {
  await Promise.allSettled([
    _renderScenarioList(),
    _renderResults(),
    _renderDrift(),
  ]);
  _wireSelectAll();
}

// ── Scenario list ─────────────────────────────────────────────────────────────

async function _renderScenarioList() {
  const el = document.getElementById('bench-scenario-list');
  if (!el) return;

  const [scenData, reportData] = await Promise.all([
    http.get(PATHS.benchmark.scenarios).catch(() => ({ scenarios: [] })),
    http.get(PATHS.benchmark.report).catch(() => null),
  ]);

  const names   = scenData.scenarios ?? [];
  const results = reportData?.results ?? [];
  const byName  = Object.fromEntries(results.map(r => [r.scenario, r]));

  if (!names.length) {
    el.innerHTML = '<div class="bench-scenario-row" style="color:var(--text3)">No scenarios found.</div>';
    return;
  }

  el.innerHTML = names.map(n => {
    const last = byName[n];
    let pill = '';
    if (last) {
      const ok = last.status === 'done';
      const qs = last.quality_score != null ? ` · ${(last.quality_score * 100).toFixed(0)}%` : '';
      pill = `<span class="bench-scenario-last ${ok ? 'ok' : 'fail'}">${ok ? '✓' : '✗'}${qs}</span>`;
    } else {
      pill = `<span class="bench-scenario-last none">New</span>`;
    }
    return `
      <label class="bench-scenario-row">
        <input type="checkbox" class="bench-chk" value="${_esc(n)}" checked />
        <span class="bench-scenario-name">${_esc(n)}</span>
        ${pill}
      </label>`;
  }).join('');
}

function _wireSelectAll() {
  const allChk = document.getElementById('bench-chk-all');
  if (!allChk) return;
  allChk.addEventListener('change', () => {
    document.querySelectorAll('.bench-chk').forEach(c => { c.checked = allChk.checked; });
  });
  document.getElementById('bench-scenario-list')?.addEventListener('change', () => {
    const all   = document.querySelectorAll('.bench-chk');
    const checked = document.querySelectorAll('.bench-chk:checked');
    allChk.indeterminate = checked.length > 0 && checked.length < all.length;
    allChk.checked       = checked.length === all.length;
  });
}

// ── Results ───────────────────────────────────────────────────────────────────

async function _renderResults() {
  const el      = document.getElementById('bench-results-table');
  const statsBar = document.getElementById('bench-stats-bar');
  if (!el) return;

  const data    = await http.get(PATHS.benchmark.report).catch(() => null);
  const results = data?.results ?? [];

  if (!results.length) {
    el.innerHTML = `
      <div class="bench-empty-state">
        <div class="bench-empty-icon">⚡</div>
        <div class="bench-empty-text">No results yet</div>
        <div class="bench-empty-hint">Select scenarios and click <strong>Run All</strong> to start</div>
      </div>`;
    if (statsBar) statsBar.classList.add('hidden');
    return;
  }

  // Update stats bar
  const passed  = results.filter(r => r.status === 'done').length;
  const failed  = results.length - passed;
  const pct     = Math.round((passed / results.length) * 100);
  const avgQs   = results.filter(r => r.quality_score != null);
  const qs      = avgQs.length
    ? `${(avgQs.reduce((s, r) => s + r.quality_score, 0) / avgQs.length * 100).toFixed(0)}%`
    : '—';

  document.getElementById('bstat-total')?.setAttribute('data-v', results.length) ||
    (document.getElementById('bstat-total') && (document.getElementById('bstat-total').textContent = results.length));
  _setStat('bstat-total',   results.length);
  _setStat('bstat-passed',  passed);
  _setStat('bstat-failed',  failed);
  _setStat('bstat-quality', qs);
  const bar = document.getElementById('bstat-bar');
  if (bar) bar.style.width = `${pct}%`;
  if (statsBar) statsBar.classList.remove('hidden');

  const rows = results.map(r => {
    const tokens = (r.total_prompt_tokens ?? 0) + (r.total_completion_tokens ?? 0);
    const wall   = r.wall_ms != null ? `${(r.wall_ms / 1000).toFixed(1)}s` : '—';
    const ok     = r.status === 'done';
    const qs     = r.quality_score != null ? `${(r.quality_score * 100).toFixed(0)}%` : '—';
    return `<tr>
      <td style="font-weight:500">${_esc(r.scenario)}</td>
      <td><span class="bench-pill ${ok ? 'ok' : 'fail'}">${ok ? '✓ pass' : '✗ fail'}</span></td>
      <td style="color:var(--text2)">${tokens.toLocaleString()}</td>
      <td style="color:var(--text2)">${wall}</td>
      <td style="color:var(--text2)">${qs}</td>
    </tr>`;
  }).join('');

  el.innerHTML = `<table class="bench-results-table">
    <thead><tr>
      <th>Scenario</th><th>Status</th><th>Tokens</th><th>Wall Time</th><th>Quality</th>
    </tr></thead>
    <tbody>${rows}</tbody>
  </table>`;
}

function _setStat(id, val) {
  const el = document.getElementById(id);
  if (el) el.textContent = val;
}

// ── History drift ─────────────────────────────────────────────────────────────

async function _renderDrift() {
  const el = document.getElementById('bench-drift-summary');
  if (!el) return;

  const data    = await http.get(PATHS.benchmark.history).catch(() => null);
  const history = data?.history ?? [];

  if (history.length < 2) {
    el.innerHTML = `
      <div class="bench-empty-state bench-empty-sm">
        <div class="bench-empty-text">Need ≥ 2 runs to compute drift</div>
        <div class="bench-empty-hint">Run the benchmark again after the first run</div>
      </div>`;
    return;
  }

  const latest  = history[history.length - 1]?.results ?? [];
  const prev    = history[history.length - 2]?.results ?? [];
  const byName  = Object.fromEntries(prev.map(r => [r.scenario, r]));

  const rows = latest.map(r => {
    const p      = byName[r.scenario];
    if (!p) return '';
    const curTok = (r.total_prompt_tokens ?? 0) + (r.total_completion_tokens ?? 0);
    const preTok = (p.total_prompt_tokens ?? 0) + (p.total_completion_tokens ?? 0);
    const drift  = preTok > 0 ? ((curTok - preTok) / preTok * 100) : null;
    if (drift === null) return '';
    const isPos   = drift > 0;
    const isBig   = Math.abs(drift) > 20;
    const arrow   = drift > 0.5 ? '▲' : drift < -0.5 ? '▼' : '→';
    const cls     = isBig ? (isPos ? 'bench-fail' : 'bench-ok') : '';
    return `<tr>
      <td style="font-weight:500">${_esc(r.scenario)}</td>
      <td class="${cls}" style="font-variant-numeric:tabular-nums">
        ${arrow} ${drift > 0 ? '+' : ''}${drift.toFixed(1)}%
      </td>
      <td style="color:var(--text3);font-size:12px">${preTok.toLocaleString()} → ${curTok.toLocaleString()}</td>
    </tr>`;
  }).filter(Boolean).join('');

  el.innerHTML = rows
    ? `<table class="bench-results-table">
         <thead><tr><th>Scenario</th><th>Token Δ</th><th>Tokens</th></tr></thead>
         <tbody>${rows}</tbody>
       </table>`
    : `<div class="bench-empty-state bench-empty-sm">
         <div class="bench-empty-text">No comparable runs found</div>
       </div>`;
}

// ── Run scenarios ─────────────────────────────────────────────────────────────

function _selectedScenarios() {
  return [...document.querySelectorAll('.bench-chk:checked')].map(el => el.value);
}

export async function runAll()      { await _run(null); }
export async function runSelected() {
  const sel = _selectedScenarios();
  if (!sel.length) { _cb.onToast('No scenarios selected'); return; }
  await _run(sel);
}

async function _run(scenarios) {
  const progressEl  = document.getElementById('bench-progress');
  const logHeader   = document.getElementById('bench-log-header');
  const badgeEl     = document.getElementById('bench-status-badge');
  const spinner     = document.getElementById('bench-log-spinner');

  if (badgeEl)    { badgeEl.textContent = 'RUNNING'; badgeEl.className = 'plan-badge running'; }
  if (progressEl) progressEl.innerHTML = '';
  if (logHeader)  logHeader.classList.remove('hidden');
  if (spinner)    spinner.style.display = '';

  const start = Date.now();
  const resp  = await fetch(PATHS.benchmark.run, {
    method:  'POST',
    headers: { 'Content-Type': 'application/json' },
    body:    JSON.stringify({ scenarios }),
  });

  const reader  = resp.body.getReader();
  const decoder = new TextDecoder();
  let   buf     = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    const lines = buf.split('\n');
    buf = lines.pop();
    for (const line of lines) {
      if (!line.startsWith('data: ')) continue;
      const msg = JSON.parse(line.slice(6));

      if (msg.scenario && progressEl) {
        const ok      = msg.result?.status === 'done';
        const elapsed = ((Date.now() - start) / 1000).toFixed(1);
        const row     = document.createElement('div');
        row.className = 'bench-progress-row';
        row.innerHTML = `
          <span class="bench-progress-status ${ok ? 'bench-ok' : 'bench-fail'}">${ok ? '✓' : '✗'}</span>
          <span>${_esc(msg.scenario)}</span>
          <span class="bench-progress-time">${elapsed}s</span>`;
        progressEl.appendChild(row);
        progressEl.scrollTop = progressEl.scrollHeight;
      }

      if (msg.done) {
        if (badgeEl) { badgeEl.textContent = 'IDLE'; badgeEl.className = 'plan-badge'; }
        if (spinner) spinner.style.display = 'none';
        _cb.onToast(`Benchmark complete — ${msg.total} scenario(s)`);
        await init();
        await updateWorkstationCard();
      }
    }
  }
}

// ── Clear ─────────────────────────────────────────────────────────────────────

export async function clearReport() {
  await fetch(PATHS.benchmark.clear, { method: 'DELETE' });
  _cb.onToast('Benchmark data cleared');
  const statsBar = document.getElementById('bench-stats-bar');
  if (statsBar) statsBar.classList.add('hidden');
  const logHeader = document.getElementById('bench-log-header');
  if (logHeader) logHeader.classList.add('hidden');
  await init();
  await updateWorkstationCard();
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function _esc(s) {
  return String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}
