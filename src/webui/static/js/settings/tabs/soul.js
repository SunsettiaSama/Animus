import * as soulMod from '../../modules/soul.js';
import { _v, _c, _si, _sc } from './_helpers.js';

function _num(id, fallback = 0) {
  const n = parseFloat(_v(id));
  return Number.isFinite(n) ? n : fallback;
}

function _int(id, fallback = 0) {
  const n = parseInt(_v(id), 10);
  return Number.isFinite(n) ? n : fallback;
}

export async function load() {
  const [soul, mem, infra] = await Promise.all([
    soulMod.loadConfig().catch(() => null),
    soulMod.loadMemoryConfig().catch(() => null),
    soulMod.loadInfraConfig().catch(() => null),
  ]);

  if (soul?.config) {
    const c = soul.config;
    const hb = c.heartbeat ?? {};
    const lm = c.landmark ?? {};
    const wand = c.wander ?? {};
    const sp = c.speak ?? {};
    const pr = c.presence ?? {};
    const exp = pr.expectation ?? {};
    const aux = c.llm_aux ?? {};
    const life = c.life ?? {};

    _si('s-soul-hb-scan', hb.scan_interval_sec);
    _si('s-soul-hb-active-start', hb.active_hours_start ?? '08:00');
    _si('s-soul-hb-active-end', hb.active_hours_end ?? '22:00');
    _si('s-soul-hb-active-tz', hb.active_timezone ?? 'Asia/Shanghai');
    _si('s-soul-hb-forget', hb.memory_forget_interval_sec);
    _si('s-soul-hb-memory-sleep', hb.memory_sleep_at ?? '04:00');
    _si('s-soul-hb-ruminate', hb.memory_ruminate_interval_sec);
    _si('s-soul-hb-surprise', hb.surprise_tick_interval_sec);
    _si('s-soul-hb-drift-day', hb.persona_drift_day_of_month);
    _si('s-soul-hb-drift-at', hb.persona_drift_at);
    _si('s-soul-hb-drift-days', hb.persona_drift_interval_days);

    _si('s-soul-lm-window', lm.write_window_hours);
    _si('s-soul-lm-max', lm.write_max_per_window);
    _si('s-soul-lm-interval', lm.write_interval_sec);
    _si('s-soul-lm-trigger', lm.trigger_interval_sec);
    _si('s-soul-lm-gap', lm.write_gap_rounds);

    _si('s-soul-wander-floor', wand.drift_intensity_floor);
    _si('s-soul-wander-interval', wand.interval_sec);

    _si('s-soul-speak-idle', sp.session_idle_sec);
    _sc('s-soul-speak-segment', (sp.stream_flush_mode ?? 'segment') === 'segment');
    _si('s-soul-speak-share-th', sp.share_proactive_threshold);
    _si('s-soul-speak-distill', sp.context_distill_chunk_size);

    _si('s-soul-pres-wake', pr.wake_at);
    _si('s-soul-pres-proactive', exp.proactive_open_threshold);
    _si('s-soul-pres-reply', exp.reply_urge_threshold);

    _si('s-soul-aux-life', aux.life);
    _si('s-soul-aux-persona', aux.persona);
    _si('s-soul-aux-memory', aux.memory);
    _si('s-soul-aux-presence', aux.presence);
    _si('s-soul-aux-speak', aux.speak);

    _si('s-soul-life-chronicle', life.chronicle_salient_threshold);
  }

  if (mem?.config) {
    const c = mem.config;
    const st = c.short_term ?? {};
    const lt = c.long_term ?? {};
    const svc = c.service ?? {};
    _si('s-soul-mem-st-half', st.half_life_days);
    _si('s-soul-mem-lt-half', lt.half_life_days);
    _si('s-soul-mem-forget', lt.forget_threshold);
    _sc('s-soul-mem-async', svc.async_ingest ?? true);
    _si('s-soul-mem-recall-k', svc.recall_top_k);
    _si('s-soul-mem-narrative', svc.narrative_threshold);
  }

  if (infra?.config) {
    const c = infra.config;
    const vec = c.vector ?? {};
    const emb = c.embedding ?? {};
    _sc('s-soul-infra-enabled', c.enabled ?? true);
    _si('s-soul-infra-qdrant', vec.qdrant_path);
    _si('s-soul-infra-collection', vec.collection_name);
    _si('s-soul-infra-model', emb.model_name_or_path);
    _si('s-soul-infra-device', emb.device);
  }
}

export async function save() {
  const soulConfig = {
    heartbeat: {
      scan_interval_sec: _num('s-soul-hb-scan', 300),
      active_hours_start: _v('s-soul-hb-active-start') || '08:00',
      active_hours_end: _v('s-soul-hb-active-end') || '22:00',
      active_timezone: _v('s-soul-hb-active-tz') || 'Asia/Shanghai',
      memory_forget_interval_sec: _num('s-soul-hb-forget', 21600),
      memory_sleep_at: _v('s-soul-hb-memory-sleep') || '04:00',
      memory_ruminate_interval_sec: _num('s-soul-hb-ruminate', 3600),
      surprise_tick_interval_sec: _num('s-soul-hb-surprise', 300),
      persona_drift_day_of_month: _int('s-soul-hb-drift-day', 1),
      persona_drift_at: _v('s-soul-hb-drift-at') || '03:00',
      persona_drift_interval_days: _num('s-soul-hb-drift-days', 30),
    },
    landmark: {
      write_window_hours: _num('s-soul-lm-window', 6),
      write_max_per_window: _int('s-soul-lm-max', 2),
      write_interval_sec: _num('s-soul-lm-interval', 3600),
      trigger_interval_sec: _num('s-soul-lm-trigger', 300),
      write_gap_rounds: _int('s-soul-lm-gap', 3),
    },
    wander: {
      drift_intensity_floor: _num('s-soul-wander-floor', 0.05),
      interval_sec: _num('s-soul-wander-interval', 3600),
    },
    speak: {
      session_idle_sec: _num('s-soul-speak-idle', 3600),
      stream_flush_mode: _c('s-soul-speak-segment') ? 'segment' : 'token_batch',
      share_proactive_threshold: _num('s-soul-speak-share-th', 0.65),
      context_distill_chunk_size: _int('s-soul-speak-distill', 4),
    },
    presence: {
      wake_at: _v('s-soul-pres-wake') || '08:00',
      expectation: {
        proactive_open_threshold: _num('s-soul-pres-proactive', 0.65),
        reply_urge_threshold: _num('s-soul-pres-reply', 0.35),
      },
    },
    llm_aux: {
      life: _v('s-soul-aux-life') || 'life',
      persona: _v('s-soul-aux-persona') || 'persona',
      memory: _v('s-soul-aux-memory') || 'memory',
      presence: _v('s-soul-aux-presence') || 'presence',
      speak: _v('s-soul-aux-speak') || 'speak',
    },
    life: {
      chronicle_salient_threshold: _num('s-soul-life-chronicle', 0.55),
    },
  };

  const memConfig = {
    short_term: { half_life_days: _num('s-soul-mem-st-half', 3) },
    long_term: {
      half_life_days: _num('s-soul-mem-lt-half', 30),
      forget_threshold: _num('s-soul-mem-forget', 0.05),
    },
    service: {
      async_ingest: _c('s-soul-mem-async'),
      recall_top_k: _int('s-soul-mem-recall-k', 5),
      narrative_threshold: _num('s-soul-mem-narrative', 0.65),
    },
  };

  const infraConfig = {
    enabled: _c('s-soul-infra-enabled'),
    vector: {
      qdrant_path: _v('s-soul-infra-qdrant'),
      collection_name: _v('s-soul-infra-collection'),
    },
    embedding: {
      model_name_or_path: _v('s-soul-infra-model'),
      device: _v('s-soul-infra-device') || 'auto',
    },
  };

  await soulMod.saveConfig(soulConfig);
  await soulMod.saveMemoryConfig(memConfig);
  await soulMod.saveInfraConfig(infraConfig);
}
