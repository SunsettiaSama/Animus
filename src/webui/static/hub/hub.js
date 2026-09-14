/**
 * hub.js — 启动站前端逻辑（原生 JS，无外部依赖）。
 *
 * 只做三件事：轮询 /api/launch/status、渲染阶段灯与引导清单、
 * 更新入口卡片徽标。卡片启停交互属 Phase 2（launch.demos 上线后接入）。
 */

(() => {
  'use strict';

  const POLL_FAST_MS = 2000;   // 尚未全绿时的轮询间隔
  const POLL_SLOW_MS = 8000;   // 全绿后的巡检间隔
  let timer = null;

  const PHASE_STATE_WORDS = {
    ok: '就绪', warn: '注意', fail: '失败', pending: '等待中',
  };

  // ── 渲染 ────────────────────────────────────────────────────────────────

  function renderPhases(data) {
    const box = document.getElementById('hub-phases');
    box.innerHTML = '';
    const fullSoulError = (data.soul && data.soul.init_error) || '';
    for (const p of data.phases) {
      const el = document.createElement('div');
      el.className = 'phase';
      el.dataset.state = p.state;
      // Soul 阶段的悬停提示给完整错误原文（显示行保持短句）
      const tip = (p.id === 'soul' && fullSoulError) ? fullSoulError : (p.detail || '');
      el.innerHTML =
        `<div class="p-head"><span class="p-dot"></span>` +
        `<span class="p-label">${escapeHtml(p.label)}</span>` +
        `<span class="p-state">${PHASE_STATE_WORDS[p.state] || ''}</span></div>` +
        `<div class="p-detail" title="${escapeHtml(tip)}">` +
        `${escapeHtml(p.detail || '')}</div>`;
      box.appendChild(el);
    }

    const summary = document.getElementById('hub-phase-summary');
    if (summary) {
      const okCount = data.phases.filter(p => p.state === 'ok').length;
      const total = data.phases.length;
      summary.textContent = `${okCount}/${total} 就绪`;
      summary.dataset.tone = okCount === total ? 'ok' : 'warn';
    }
  }

  function renderChecks(checks) {
    const section = document.getElementById('hub-checks-section');
    const list = document.getElementById('hub-checks');
    if (!checks.length) {
      section.classList.add('hidden');
      return;
    }
    section.classList.remove('hidden');
    list.innerHTML = '';
    for (const c of checks) {
      const li = document.createElement('li');
      li.innerHTML =
        `<span class="c-dot"></span>` +
        `<span class="c-label">${escapeHtml(c.label)}</span>` +
        `<span class="c-hint">${escapeHtml(c.hint || '')}</span>`;
      list.appendChild(li);
    }
  }

  function renderChatBadge(data) {
    const badge = document.getElementById('badge-chat');
    if (!badge) return;
    if (data.soul_ready) {
      badge.textContent = '就绪';
      badge.dataset.state = 'ok';
    } else {
      // 冷启动是过程不是故障：统一用琥珀色，不制造红色焦虑
      badge.textContent = data.soul && data.soul.running ? '初始化中' : '等待 Soul';
      badge.dataset.state = 'warn';
    }
  }

  function markRefreshed() {
    const el = document.getElementById('hub-refreshed');
    const t = new Date().toLocaleTimeString('zh-CN', { hour12: false });
    if (el) el.textContent = `· ${t}`;
  }

  function escapeHtml(s) {
    return String(s ?? '').replace(/[&<>"']/g, ch =>
      ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));
  }

  // ── 轮询 ────────────────────────────────────────────────────────────────

  function allGreen(data) {
    return data.phases.every(p => p.state === 'ok') && data.checks.length === 0;
  }

  async function tick() {
    let nextDelay = POLL_SLOW_MS;
    try {
      const res = await fetch('/api/launch/status', { cache: 'no-store' });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      renderPhases(data);
      renderChecks(data.checks || []);
      renderChatBadge(data);
      markRefreshed();
      nextDelay = allGreen(data) ? POLL_SLOW_MS : POLL_FAST_MS;
    } catch (err) {
      // 服务重启等瞬断：保持快速重试，阶段灯交由下次成功刷新
      nextDelay = POLL_FAST_MS;
    }
    timer = setTimeout(tick, nextDelay);
  }

  document.addEventListener('visibilitychange', () => {
    // 页面回到前台立即刷一次，避免展示陈旧状态
    if (!document.hidden) {
      if (timer) clearTimeout(timer);
      tick();
    }
  });

  tick();
})();
