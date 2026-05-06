/**
 * modules/benchmark.js — Benchmark Suite screen logic.
 *
 * Responsibilities:
 *  - Render the scenario checklist (nothing pre-selected)
 *  - Drive the Run / Run-Selected / Clear actions via SSE
 *  - Render results table + drift panel
 *  - Scenario detail drawer: full metadata, last-run breakdown, metric trend sparklines
 */

import { http, PATHS } from '../api.js';

const _cb = { onToast: () => {} };
export function setCallbacks(cbs) { Object.assign(_cb, cbs); }

// ── Workstation summary card ───────────────────────────────────────────────────

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
    _renderProbeRuns(),
  ]);
  _wireSelectAll();
  _wireDetailClose();
  _wireProbeFilter();
}

// ── Scenario list (checklist, nothing pre-selected) ───────────────────────────

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
      <label class="bench-scenario-row" data-scenario="${_esc(n)}">
        <input type="checkbox" class="bench-chk" value="${_esc(n)}" />
        <span class="bench-scenario-name">${_esc(n)}</span>
        ${pill}
      </label>`;
  }).join('');

  // Click on name text → open detail (not the checkbox)
  el.querySelectorAll('.bench-scenario-name').forEach(span => {
    span.style.cursor = 'pointer';
    span.addEventListener('click', e => {
      e.preventDefault();
      e.stopPropagation();
      _openDetail(span.closest('[data-scenario]').dataset.scenario);
    });
  });
}

// ── Select-all wiring ─────────────────────────────────────────────────────────

function _wireSelectAll() {
  const allChk = document.getElementById('bench-chk-all');
  if (!allChk) return;

  // Start unchecked and indeterminate-free
  allChk.checked       = false;
  allChk.indeterminate = false;

  allChk.addEventListener('change', () => {
    document.querySelectorAll('.bench-chk').forEach(c => { c.checked = allChk.checked; });
    allChk.indeterminate = false;
  });

  document.getElementById('bench-scenario-list')?.addEventListener('change', e => {
    if (!e.target.classList.contains('bench-chk')) return;
    const all     = document.querySelectorAll('.bench-chk');
    const checked = document.querySelectorAll('.bench-chk:checked');
    if (checked.length === 0) {
      allChk.checked = false; allChk.indeterminate = false;
    } else if (checked.length === all.length) {
      allChk.checked = true;  allChk.indeterminate = false;
    } else {
      allChk.checked = false; allChk.indeterminate = true;
    }
  });
}

// ── Results table ─────────────────────────────────────────────────────────────

async function _renderResults() {
  const el       = document.getElementById('bench-results-table');
  const statsBar = document.getElementById('bench-stats-bar');
  if (!el) return;

  const data    = await http.get(PATHS.benchmark.report).catch(() => null);
  const results = data?.results ?? [];

  if (!results.length) {
    el.innerHTML = `
      <div class="bench-empty-state">
        <div class="bench-empty-icon">⚡</div>
        <div class="bench-empty-text">No results yet</div>
        <div class="bench-empty-hint">Select scenarios and click <strong>Run Selected</strong></div>
      </div>`;
    if (statsBar) statsBar.classList.add('hidden');
    return;
  }

  const passed = results.filter(r => r.status === 'done').length;
  const failed = results.length - passed;
  const pct    = Math.round((passed / results.length) * 100);
  const avgQs  = results.filter(r => r.quality_score != null);
  const qs     = avgQs.length
    ? `${(avgQs.reduce((s, r) => s + r.quality_score, 0) / avgQs.length * 100).toFixed(0)}%`
    : '—';

  _setStat('bstat-total',   results.length);
  _setStat('bstat-passed',  passed);
  _setStat('bstat-failed',  failed);
  _setStat('bstat-quality', qs);
  const bar = document.getElementById('bstat-bar');
  if (bar) bar.style.width = `${pct}%`;
  if (statsBar) statsBar.classList.remove('hidden');

  const rows = results.map(r => {
    const tokens  = (r.total_prompt_tokens ?? 0) + (r.total_completion_tokens ?? 0);
    const wall    = r.wall_ms != null ? `${(r.wall_ms / 1000).toFixed(2)}s` : '—';
    const ok      = r.status === 'done';
    const qsCell  = r.quality_score != null ? `${(r.quality_score * 100).toFixed(0)}%` : '—';
    const retries = r.llm_retries ?? 0;
    return `<tr class="bench-result-row" data-scenario="${_esc(r.scenario)}" style="cursor:pointer">
      <td style="font-weight:500">${_esc(r.scenario)}</td>
      <td><span class="bench-pill ${ok ? 'ok' : 'fail'}">${ok ? '✓' : '✗'}</span></td>
      <td style="color:var(--text2)">${tokens.toLocaleString()}</td>
      <td style="color:var(--text2)">${wall}</td>
      <td style="color:var(--text2)">${r.steps ?? '—'}</td>
      <td style="color:${retries > 0 ? '#dc2626' : 'var(--text2)'}">${retries}</td>
      <td style="color:var(--text2)">${qsCell}</td>
    </tr>`;
  }).join('');

  el.innerHTML = `<table class="bench-results-table">
    <thead><tr>
      <th>Scenario</th><th>Status</th><th>Tokens</th><th>Wall</th><th>Steps</th><th>Retries</th><th>Quality</th>
    </tr></thead>
    <tbody>${rows}</tbody>
  </table>`;

  // Click row → open detail
  el.querySelectorAll('.bench-result-row').forEach(row => {
    row.addEventListener('click', () => _openDetail(row.dataset.scenario));
  });
}

function _setStat(id, val) {
  const el = document.getElementById(id);
  if (el) el.textContent = val;
}

// ── Drift panel ───────────────────────────────────────────────────────────────

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

  // Show drift vs rolling average (last 3 runs)
  const latest = history[history.length - 1]?.results ?? [];
  const window = history.slice(Math.max(0, history.length - 4), -1)
    .flatMap(h => h.results ?? []);

  const baseline = {};
  const counts   = {};
  for (const r of window) {
    const toks = (r.total_prompt_tokens ?? 0) + (r.total_completion_tokens ?? 0);
    const rr   = (r.llm_retries ?? 0) / Math.max(r.steps ?? 1, 1);
    baseline[r.scenario] = baseline[r.scenario] ?? { toks: 0, wall: 0, rr: 0, qs: 0, qsN: 0 };
    baseline[r.scenario].toks += toks;
    baseline[r.scenario].wall += r.wall_ms ?? 0;
    baseline[r.scenario].rr   += rr;
    if (r.quality_score != null) {
      baseline[r.scenario].qs  += r.quality_score;
      baseline[r.scenario].qsN += 1;
    }
    counts[r.scenario] = (counts[r.scenario] ?? 0) + 1;
  }

  const rows = latest.map(r => {
    const n  = counts[r.scenario];
    if (!n) return '';
    const b  = baseline[r.scenario];
    const avgToks = b.toks / n;
    const curToks = (r.total_prompt_tokens ?? 0) + (r.total_completion_tokens ?? 0);
    const dToks   = avgToks > 0 ? ((curToks - avgToks) / avgToks * 100) : null;

    const avgRR   = b.rr / n;
    const curRR   = (r.llm_retries ?? 0) / Math.max(r.steps ?? 1, 1);
    const dRR     = avgRR > 0.001 ? ((curRR - avgRR) / avgRR * 100) : null;

    const makeCell = (d, invertSign) => {
      if (d === null) return '<td style="color:var(--text3)">—</td>';
      const isBig = Math.abs(d) > 15;
      const bad   = invertSign ? d > 0 : d < 0;  // higher tokens = bad; higher quality = good
      const cls   = isBig ? (bad ? 'bench-fail' : 'bench-ok') : '';
      const arrow = d > 0.5 ? '▲' : d < -0.5 ? '▼' : '→';
      return `<td class="${cls}" style="font-variant-numeric:tabular-nums">${arrow} ${d > 0 ? '+' : ''}${d.toFixed(1)}%</td>`;
    };

    return `<tr class="bench-result-row" data-scenario="${_esc(r.scenario)}" style="cursor:pointer">
      <td style="font-weight:500">${_esc(r.scenario)}</td>
      ${makeCell(dToks, true)}
      ${makeCell(dRR, true)}
    </tr>`;
  }).filter(Boolean).join('');

  el.innerHTML = rows
    ? `<table class="bench-results-table">
         <thead><tr><th>Scenario</th><th>Token Δ</th><th>Retry-rate Δ</th></tr></thead>
         <tbody>${rows}</tbody>
       </table>`
    : `<div class="bench-empty-state bench-empty-sm">
         <div class="bench-empty-text">No comparable runs found</div>
       </div>`;

  el.querySelectorAll('.bench-result-row').forEach(row => {
    row.addEventListener('click', () => _openDetail(row.dataset.scenario));
  });
}

// ── Scenario detail drawer ────────────────────────────────────────────────────

let _detailOpen = null;

function _wireDetailClose() {
  document.getElementById('bench-detail-close')?.addEventListener('click', _closeDetail);
}

function _closeDetail() {
  const col = document.getElementById('bench-detail-col');
  if (col) col.classList.add('hidden');
  _detailOpen = null;
}

async function _openDetail(name) {
  if (_detailOpen === name) { _closeDetail(); return; }
  _detailOpen = name;

  const col   = document.getElementById('bench-detail-col');
  const title = document.getElementById('bench-detail-title');
  const body  = document.getElementById('bench-detail-body');
  if (!col || !body) return;

  col.classList.remove('hidden');
  title.textContent = name;
  body.innerHTML = '<div class="bench-detail-loading">Loading…</div>';

  const [detail, trendQ, trendRR] = await Promise.all([
    http.get(PATHS.benchmark.scenarioDetail(name)).catch(() => null),
    http.get(PATHS.benchmark.trend('quality_score', name)).catch(() => null),
    http.get(PATHS.benchmark.trend('retry_rate',    name)).catch(() => null),
  ]);

  if (!detail) {
    body.innerHTML = '<div class="bench-detail-error">Failed to load scenario.</div>';
    return;
  }

  const r = detail.last_result;

  // ── Input section ─────────────────────────────────────────────────────────
  const promptHtml = `
    <div class="bench-detail-section">
      <div class="bench-detail-section-title">Input Prompt</div>
      <div class="bench-detail-prompt">${_esc(detail.prompt)}</div>
    </div>`;

  // ── Description ──────────────────────────────────────────────────────────
  const descHtml = detail.description ? `
    <div class="bench-detail-section">
      <div class="bench-detail-section-title">Description</div>
      <div class="bench-detail-desc">${_esc(detail.description.trim())}</div>
    </div>` : '';

  // ── Spec ──────────────────────────────────────────────────────────────────
  const specRows = [];
  specRows.push(`<div class="bench-kv"><span>LLM script steps</span><span>${detail.llm_script_count}</span></div>`);
  if (detail.tool_names?.length) {
    specRows.push(`<div class="bench-kv"><span>Tools used</span><span>${detail.tool_names.map(_esc).join(', ')}</span></div>`);
  }
  if (detail.delay_ms) specRows.push(`<div class="bench-kv"><span>Simulated delay</span><span>${detail.delay_ms} ms</span></div>`);

  const expRows = [];
  const exp = detail.expected ?? {};
  if (exp.final_output_contains) {
    expRows.push(`<div class="bench-kv"><span>Output contains</span><span class="bench-detail-chip">${
      [].concat(exp.final_output_contains).map(_esc).join('</span><span class="bench-detail-chip">')
    }</span></div>`);
  }
  if (exp.tool_calls_required) {
    expRows.push(`<div class="bench-kv"><span>Tools required</span><span>${
      [].concat(exp.tool_calls_required).map(_esc).join(', ')
    }</span></div>`);
  }
  if (exp.max_steps)   expRows.push(`<div class="bench-kv"><span>Max steps</span><span>${exp.max_steps}</span></div>`);
  if (detail.thresholds?.max_wall_ms)    expRows.push(`<div class="bench-kv"><span>Wall budget</span><span>${detail.thresholds.max_wall_ms} ms</span></div>`);
  if (detail.thresholds?.max_total_tokens) expRows.push(`<div class="bench-kv"><span>Token budget</span><span>${detail.thresholds.max_total_tokens}</span></div>`);

  const specHtml = `
    <div class="bench-detail-section">
      <div class="bench-detail-section-title">Spec</div>
      ${specRows.join('')}
      ${expRows.length ? '<div class="bench-detail-divider"></div>' + expRows.join('') : ''}
    </div>`;

  // ── Last run ──────────────────────────────────────────────────────────────
  let lastRunHtml = '';
  if (r) {
    const ok       = r.status === 'done';
    const tokens   = (r.total_prompt_tokens ?? 0) + (r.total_completion_tokens ?? 0);
    const wall     = r.wall_ms != null ? `${r.wall_ms.toFixed(0)} ms` : '—';
    const qs       = r.quality_score != null ? `${(r.quality_score * 100).toFixed(0)}%` : '—';
    const retries  = r.llm_retries ?? 0;

    // Tool calls breakdown
    const toolRows = (r.tool_calls ?? []).map(tc => {
      const tOk = tc.success !== false;
      return `<div class="bench-kv bench-kv-sm">
        <span><span class="bench-pill ${tOk ? 'ok' : 'fail'}" style="font-size:10px">${tOk ? '✓' : '✗'}</span> ${_esc(tc.tool_name)}</span>
        <span style="color:var(--text3)">${tc.latency_ms?.toFixed(0) ?? '?'} ms · in ${tc.input_size} / out ${tc.output_size}</span>
      </div>`;
    }).join('');

    // LLM calls breakdown
    const llmRows = (r.llm_calls ?? []).map((c, i) => {
      return `<div class="bench-kv bench-kv-sm">
        <span>LLM call ${i + 1}</span>
        <span style="color:var(--text3)">${c.prompt_tokens}p + ${c.completion_tokens}c tokens · ${c.latency_ms?.toFixed(0) ?? '?'} ms</span>
      </div>`;
    }).join('');

    lastRunHtml = `
      <div class="bench-detail-section">
        <div class="bench-detail-section-title">
          Last Run
          <span class="bench-pill ${ok ? 'ok' : 'fail'}" style="margin-left:6px">${ok ? '✓ pass' : '✗ fail'}</span>
        </div>
        <div class="bench-kv"><span>Wall time</span><span>${wall}</span></div>
        <div class="bench-kv"><span>Steps</span><span>${r.steps ?? '—'}</span></div>
        <div class="bench-kv"><span>Tokens</span><span>${tokens.toLocaleString()} (${r.total_prompt_tokens ?? 0}p + ${r.total_completion_tokens ?? 0}c)</span></div>
        <div class="bench-kv"><span>Retries (L2)</span><span style="color:${retries > 0 ? '#dc2626' : 'inherit'}">${retries}</span></div>
        <div class="bench-kv"><span>Quality score</span><span>${qs}</span></div>
        ${r.error ? `<div class="bench-kv"><span>Error</span><span style="color:#dc2626">${_esc(r.error)}</span></div>` : ''}
        ${llmRows ? `<div class="bench-detail-divider"></div><div class="bench-kv-label">LLM Calls</div>${llmRows}` : ''}
        ${toolRows ? `<div class="bench-detail-divider"></div><div class="bench-kv-label">Tool Calls</div>${toolRows}` : ''}
      </div>`;
  } else {
    lastRunHtml = `
      <div class="bench-detail-section">
        <div class="bench-detail-section-title">Last Run</div>
        <div style="color:var(--text3);font-size:13px">No results yet for this scenario.</div>
      </div>`;
  }

  // ── Trend sparklines ──────────────────────────────────────────────────────
  const trendHtml = _buildTrendHtml(
    trendQ?.series?.[name]  ?? [],
    trendRR?.series?.[name] ?? [],
  );

  body.innerHTML = descHtml + promptHtml + specHtml + lastRunHtml + trendHtml;
}

function _buildTrendHtml(qsPoints, rrPoints) {
  if (!qsPoints.length && !rrPoints.length) return '';

  const sparkline = (points, label, color, minY = 0, maxY = 1) => {
    if (!points.length) return '';
    const W = 200, H = 40, PAD = 4;
    const vals = points.map(p => p.value);
    const lo   = Math.min(...vals, minY);
    const hi   = Math.max(...vals, maxY);
    const range = hi - lo || 1;

    const toX = i => PAD + (i / Math.max(points.length - 1, 1)) * (W - PAD * 2);
    const toY = v => H - PAD - ((v - lo) / range) * (H - PAD * 2);

    const pts = points.map((p, i) => `${toX(i).toFixed(1)},${toY(p.value).toFixed(1)}`).join(' ');
    const lastVal = vals[vals.length - 1];
    const fmt = label === 'Quality' ? `${(lastVal * 100).toFixed(0)}%` : lastVal.toFixed(3);

    return `
      <div class="bench-sparkline-wrap">
        <div class="bench-sparkline-label">${label} <span style="color:${color};font-weight:600">${fmt}</span></div>
        <svg viewBox="0 0 ${W} ${H}" class="bench-sparkline">
          <polyline points="${pts}" fill="none" stroke="${color}" stroke-width="1.5" stroke-linejoin="round"/>
          <circle cx="${toX(points.length - 1).toFixed(1)}" cy="${toY(lastVal).toFixed(1)}" r="2.5" fill="${color}"/>
        </svg>
        <div class="bench-sparkline-range">${points.length} run(s)</div>
      </div>`;
  };

  return `
    <div class="bench-detail-section">
      <div class="bench-detail-section-title">Metric Trend</div>
      <div class="bench-sparklines">
        ${sparkline(qsPoints, 'Quality', '#16a34a')}
        ${sparkline(rrPoints, 'Retry-rate', '#dc2626', 0, 0.5)}
      </div>
    </div>`;
}

// ── Run logic ─────────────────────────────────────────────────────────────────

function _selectedScenarios() {
  return [...document.querySelectorAll('.bench-chk:checked')].map(el => el.value);
}

export async function runAll()      { await _run(null); }
export async function runSelected() {
  const sel = _selectedScenarios();
  if (!sel.length) { _cb.onToast('No scenarios selected — tick at least one'); return; }
  await _run(sel);
}

async function _run(scenarios) {
  const progressEl = document.getElementById('bench-progress');
  const logHeader  = document.getElementById('bench-log-header');
  const badgeEl    = document.getElementById('bench-status-badge');
  const spinner    = document.getElementById('bench-log-spinner');

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
        const retries = msg.result?.llm_retries ?? 0;
        const row     = document.createElement('div');
        row.className = 'bench-progress-row';
        row.style.cursor = 'pointer';
        row.dataset.scenario = msg.scenario;
        row.innerHTML = `
          <span class="bench-progress-status ${ok ? 'bench-ok' : 'bench-fail'}">${ok ? '✓' : '✗'}</span>
          <span>${_esc(msg.scenario)}</span>
          ${retries > 0 ? `<span style="color:#dc2626;font-size:11px">↺${retries}</span>` : ''}
          <span class="bench-progress-time">${elapsed}s</span>`;
        row.addEventListener('click', () => _openDetail(msg.scenario));
        progressEl.appendChild(row);
        progressEl.scrollTop = progressEl.scrollHeight;
      }

      if (msg.done) {
        if (badgeEl) { badgeEl.textContent = 'IDLE'; badgeEl.className = 'plan-badge'; }
        if (spinner) spinner.style.display = 'none';
        _cb.onToast(`Benchmark complete — ${msg.total} scenario(s)`);
        await init();
        await updateWorkstationCard();
        // Refresh detail if open
        if (_detailOpen) _openDetail(_detailOpen);
      }
    }
  }
}

// ── Probe runs ────────────────────────────────────────────────────────────────

let _probeTag  = '';
let _probeName = '';

function _wireProbeFilter() {
  const tagInput  = document.getElementById('bench-probe-filter-tag');
  const nameInput = document.getElementById('bench-probe-filter-name');
  const clearBtn  = document.getElementById('bench-probe-clear');

  tagInput?.addEventListener('input', () => {
    _probeTag = tagInput.value.trim();
    _renderProbeRuns();
  });
  nameInput?.addEventListener('input', () => {
    _probeName = nameInput.value.trim();
    _renderProbeRuns();
  });
  clearBtn?.addEventListener('click', async () => {
    await fetch(PATHS.probe.clear(), { method: 'DELETE' });
    _renderProbeRuns();
  });
}

async function _renderProbeRuns() {
  const el = document.getElementById('bench-probe-list');
  if (!el) return;

  const url  = PATHS.probe.runs(100, _probeTag, _probeName);
  const data = await http.get(url).catch(() => null);
  const runs = data?.runs ?? [];

  if (!runs.length) {
    el.innerHTML = `
      <div class="bench-empty-state bench-empty-sm">
        <div class="bench-empty-text">No probe runs${_probeTag || _probeName ? ' matching filter' : ''}</div>
        <div class="bench-empty-hint">Run atomic_tool benchmark or use @probe in your code</div>
      </div>`;
    return;
  }

  el.innerHTML = runs.map(r => {
    const ok      = r.status === 'ok';
    const wall    = `${r.wall_ms.toFixed(2)}ms`;
    const mCount  = Object.keys(r.metrics ?? {}).length;
    const tagHtml = r.tags.map(t => `<span class="bench-probe-tag">${_esc(t)}</span>`).join('');
    return `<div class="bench-probe-row" data-run-id="${_esc(r.run_id)}" style="cursor:pointer">
      <div class="bench-probe-row-top">
        <span class="bench-pill ${ok ? 'ok' : 'fail'}" style="font-size:10px">${ok ? '✓' : '✗'}</span>
        <span class="bench-probe-name">${_esc(r.probe_name)}</span>
        <span class="bench-probe-wall">${wall}</span>
      </div>
      <div class="bench-probe-row-tags">
        ${tagHtml}
        ${mCount ? `<span class="bench-probe-tag bench-probe-tag-metric">${mCount} metric${mCount !== 1 ? 's' : ''}</span>` : ''}
      </div>
    </div>`;
  }).join('');

  el.querySelectorAll('.bench-probe-row').forEach(row => {
    row.addEventListener('click', () => _openProbeDetail(row.dataset.runId, runs));
  });
}

function _openProbeDetail(runId, runs) {
  const run = runs.find(r => r.run_id === runId);
  if (!run) return;

  _detailOpen = `probe:${runId}`;
  const col   = document.getElementById('bench-detail-col');
  const title = document.getElementById('bench-detail-title');
  const body  = document.getElementById('bench-detail-body');
  if (!col || !body) return;

  col.classList.remove('hidden');
  title.textContent = run.probe_name;

  const ok = run.status === 'ok';
  const tsShort = run.timestamp ? run.timestamp.replace('T', ' ').slice(0, 19) + ' UTC' : '—';

  // ── Description ──────────────────────────────────────────────────────────
  const descHtml = run.description ? `
    <div class="bench-detail-section">
      <div class="bench-detail-section-title">Description</div>
      <div class="bench-detail-desc">${_esc(run.description)}</div>
    </div>` : '';

  // ── Tags ──────────────────────────────────────────────────────────────────
  const tagsHtml = run.tags?.length ? `
    <div class="bench-detail-section">
      <div class="bench-detail-section-title">Tags</div>
      <div style="display:flex;flex-wrap:wrap;gap:4px">
        ${run.tags.map(t => `<span class="bench-probe-tag">${_esc(t)}</span>`).join('')}
      </div>
    </div>` : '';

  // ── Inputs ────────────────────────────────────────────────────────────────
  const inputRows = Object.entries(run.inputs ?? {}).map(([k, v]) =>
    `<div class="bench-kv"><span>${_esc(k)}</span><span class="bench-detail-chip">${_esc(v)}</span></div>`
  ).join('');
  const inputsHtml = `
    <div class="bench-detail-section">
      <div class="bench-detail-section-title">Inputs</div>
      ${inputRows || '<div style="color:var(--text3);font-size:12px">—</div>'}
    </div>`;

  // ── Output ────────────────────────────────────────────────────────────────
  const outputHtml = `
    <div class="bench-detail-section">
      <div class="bench-detail-section-title">
        Output
        <span class="bench-pill ${ok ? 'ok' : 'fail'}" style="font-size:9px">${ok ? 'ok' : 'error'}</span>
      </div>
      ${ok
        ? `<div class="bench-detail-prompt" style="font-size:12px">${_esc(run.output ?? '—')}</div>`
        : `<div class="bench-detail-prompt" style="font-size:12px;color:#dc2626">${_esc(run.error ?? '—')}</div>`
      }
    </div>`;

  // ── Metrics ───────────────────────────────────────────────────────────────
  const metrics = run.metrics ?? {};
  const metricRows = Object.entries(metrics).map(([k, v]) => {
    const vStr = typeof v === 'boolean' ? (v ? 'true ✓' : 'false ✗') : String(v);
    const color = k === 'assertion_ok'
      ? (v ? '#16a34a' : '#dc2626')
      : 'var(--text)';
    return `<div class="bench-kv">
      <span>${_esc(k)}</span>
      <span style="font-family:var(--font-mono,monospace);color:${color}">${_esc(vStr)}</span>
    </div>`;
  }).join('');

  const metricsHtml = `
    <div class="bench-detail-section">
      <div class="bench-detail-section-title">
        Metrics
        <span style="font-weight:400;text-transform:none;letter-spacing:0;color:var(--text3)">emit_metric() calls</span>
      </div>
      ${metricRows || '<div style="color:var(--text3);font-size:12px">No metrics emitted</div>'}
      <div class="bench-detail-divider"></div>
      <div class="bench-kv"><span>wall time</span><span>${run.wall_ms.toFixed(3)} ms</span></div>
      <div class="bench-kv"><span>run id</span><span style="font-family:monospace;color:var(--text3)">${run.run_id}</span></div>
      <div class="bench-kv"><span>timestamp</span><span style="color:var(--text3)">${tsShort}</span></div>
    </div>`;

  body.innerHTML = descHtml + tagsHtml + inputsHtml + outputHtml + metricsHtml;
}

// ── Clear ─────────────────────────────────────────────────────────────────────

export async function clearReport() {
  await fetch(PATHS.benchmark.clear, { method: 'DELETE' });
  _cb.onToast('Benchmark data cleared');
  _closeDetail();
  document.getElementById('bench-stats-bar')?.classList.add('hidden');
  document.getElementById('bench-log-header')?.classList.add('hidden');
  const progress = document.getElementById('bench-progress');
  if (progress) progress.innerHTML = '';
  await init();
  await updateWorkstationCard();
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function _esc(s) {
  return String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}
