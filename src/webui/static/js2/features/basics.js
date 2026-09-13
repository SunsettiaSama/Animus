/**
 * features/basics.js — 基础配置域数据门面（LLM/Memory/Persona/Soul/Voice/Bot/Infra）。
 *
 * 合并旧 modules/ 下六个小数据模块的读取面；设置弹窗 tabs 与工作站卡片共用。
 * 端点全部来自 protocol/http_api.js。
 */

import { API } from '../protocol/http_api.js';
import { http } from '../transport/http.js';
import { bus, EVENTS } from '../store/bus.js';
import * as sessionStore from '../store/session_store.js';

const _toast = text => bus.emit(EVENTS.toastShow, String(text ?? ''));

// ── LLM ─────────────────────────────────────────────────────────────────────

export const llmMod = {
  async fetchStatus() {
    const data = await http.get(API.llm.status);
    sessionStore.update({ llmModel: data?.model ?? null });
    return data;
  },
  loadConfig() {
    return http.get(API.llm.config);
  },
  saveConfig(payload) {
    return http.post(API.llm.save, payload);
  },
  initLLM(payload) {
    return http.post(API.llm.init, payload);
  },
  loadAux() {
    return http.get(API.llm.aux);
  },
  /** payload: {models: {slot: {enabled, model, api_key, base_url, ...}}} */
  saveAux(payload) {
    return http.post(API.llm.auxSave, payload).then(data => {
      const applied = data?.applied ?? {};
      const bad = Object.entries(applied).filter(([, v]) => String(v).startsWith('error'));
      _toast(bad.length ? `次模型保存：${bad.length} 个槽位失败` : '次模型配置已保存并热生效');
      return data;
    });
  },
};

// ── Embedding（全局唯一权威源 config/embedding/model.yaml）───────────────────

export const embeddingMod = {
  loadConfig: () => http.get(API.embedding.config),
  saveConfig(config) {
    return http.post(API.embedding.save, { config }).then(data => {
      _toast('Embedding 配置已保存（重启后生效）');
      return data;
    });
  },
};

// ── Memory ──────────────────────────────────────────────────────────────────

export const memoryMod = {
  loadConfig() {
    return http.get(API.memory.get);
  },
  saveConfig(config) {
    return http.post(API.memory.save, config);
  },
  async consolidate() {
    const data = await http.post(API.memory.consolidate);
    _toast('Memory consolidation done');
    return data;
  },
};

// ── Persona ─────────────────────────────────────────────────────────────────

export const personaMod = {
  async loadConfig() {
    const data = await http.get(API.persona.get);
    if (data?.enabled && data?.profile?.name) {
      sessionStore.update({ personaName: data.profile.name });
    }
    return data;
  },
  async saveConfig(payload) {
    await http.post(API.persona.save, payload);
    _toast('Persona saved');
    const name = payload.enabled ? (payload.name ?? payload.profile?.name ?? null) : null;
    sessionStore.update({ personaName: name });
  },
};

// ── Soul ────────────────────────────────────────────────────────────────────

/** 渲染 readiness checklist 到容器元素。 */
function renderReadinessPanel(containerEl, data) {
  if (!containerEl || !data) return;
  const checks = data.checks ?? [];
  const rows = checks.map(c => {
    const icon = c.ok ? '✓' : (c.optional ? '○' : '✗');
    const cls = c.ok ? 'ok' : (c.optional ? 'opt' : 'fail');
    return `<div class="soul-check ${cls}">
      <span class="soul-check-icon">${icon}</span>
      <span class="soul-check-label">${c.label}</span>
      ${c.ok ? '' : `<span class="soul-check-hint">${c.hint ?? ''}</span>`}
    </div>`;
  }).join('');
  const state = data.soul_state ?? '—';
  containerEl.innerHTML = `
    <div class="soul-readiness-summary">
      <span>Soul: <b>${state}</b></span>
      <span>Speak: <b>${data.speak_ready ? 'ready' : '—'}</b></span>
    </div>
    <div class="soul-checklist">${rows}</div>`;
}

export const soulMod = {
  loadConfig: () => http.get(API.soul.config),
  saveConfig(config) {
    return http.post(API.soul.configSave, { config }).then(() => {
      _toast('Soul config saved（需 Reinit 后生效）');
    });
  },
  loadMemoryConfig: () => http.get(API.soul.memoryConfig),
  saveMemoryConfig(config) {
    return http.post(API.soul.memoryConfigSave, { config }).then(() => {
      _toast('Soul memory config saved');
    });
  },
  loadInfraConfig: () => http.get(API.soul.memoryInfra),
  saveInfraConfig(config) {
    return http.post(API.soul.memoryInfraSave, { config }).then(() => {
      _toast('Soul memory infra saved');
    });
  },
  fetchPersonaSnapshot: () => http.get(API.soul.persona).catch(() => null),
  rebuildPersona(preserveSelfConcept = false) {
    return http
      .post(API.soul.personaRebuild, { preserve_self_concept: preserveSelfConcept })
      .then(data => {
        _toast('Persona build 完成');
        return data;
      });
  },
  reloadPersona() {
    return http.post(API.soul.personaReload, {}).then(data => {
      _toast('Persona 已从磁盘 reload');
      return data;
    });
  },
  renderReadinessPanel,
};

// ── React basics（清除等遗留操作；不再是会话路径） ────────────────────────────

export const reactMod = {
  init(payload) {
    // legacy init 语义保留给设置页「Reinit」按钮。
    return http.post(API.react.reinit, payload).then(data => {
      if (data && typeof data === 'object' && data.error) throw new Error(data.error);
      _toast('ReAct initializing…');
      return data;
    }).catch(err => {
      _toast(err.message || 'Cannot reinitialize while streaming');
      throw err;
    });
  },
  clearMemory() {
    return http.post(API.react.memoryClear).then(() => _toast('Memory cleared'));
  },
  clearPersona() {
    return http.post(API.react.personaClear).then(() => _toast('Persona cleared'));
  },
};

// ── Voice ───────────────────────────────────────────────────────────────────

export const voiceCfg = {
  loadTTSConfig: () => http.get(API.voice.tts.config),
  saveTTSConfig: payload =>
    http.post(API.voice.tts.save, payload).then(() => _toast('TTS config saved')),
  loadSTTConfig: () => http.get(API.voice.stt.config),
  saveSTTConfig: payload =>
    http.post(API.voice.stt.save, payload).then(() => _toast('STT config saved')),
};

export const voiceMod = voiceCfg;

// ── Infra：vLLM / Sandbox / Bot 运行控制 ─────────────────────────────────────

export const infraMod = {
  vllm: {
    loadConfig: () => http.get(API.vllm.config),
    saveConfig: cfg => http.post(API.vllm.save, cfg),
    start: () => http.post(API.vllm.start),
    stop: () => http.post(API.vllm.stop),
    status: () => http.get(API.vllm.status),
    logs: () => http.get(API.vllm.logs),
  },
  sandbox: {
    loadConfig: () => http.get(API.sandbox.config),
    saveConfig: cfg => http.post(API.sandbox.save, cfg),
  },
  servicesRow: () => http.get(API.services.status),
};

// ── Bot / Channels ──────────────────────────────────────────────────────────

export const botMod = {
  loadConfig: () => http.get(API.bot.config),
  saveConfig: cfg => http.post(API.bot.save, cfg),
  getStatus: () => http.getRaw(API.bot.status),
  getPublicIp: () => http.getRaw(API.bot.publicIp),
  start() {
    return http.post(API.bot.start).then(d => {
      _toast('Bot starting…');
      return d;
    });
  },
  stop() {
    return http.post(API.bot.stop).then(d => {
      _toast('Bot stopped');
      return d;
    });
  },
};
