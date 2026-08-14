/**
 * screens/landing.js — Workstation / Landing screen logic.
 *
 * Single conversation entry; Plan/Benchmark/Scheduler are tool views only.
 */

import { goPlan, goBenchmark, goScheduler } from '../router.js';

let _modules = null;

export function registerModules(mods) {
  _modules = mods;
}

/** Refresh all workstation summary cards. */
export async function loadWorkstation() {
  if (!_modules) return;
  const {
    llmMod, reactMod, memoryMod, personaMod,
    voiceMod, schedulerMod, benchMod, botMod, infraMod,
  } = _modules;

  await Promise.allSettled([
    llmMod.updateWorkstationCard(),
    reactMod.updateWorkstationCard(),
    memoryMod.updateWorkstationCard(),
    personaMod.updateWorkstationCard(),
    voiceMod.updateWorkstationCard(),
    schedulerMod.updateWorkstationCard(),
    benchMod.updateWorkstationCard(),
    botMod.updateWorkstationCard(),
    infraMod.updateServicesRow(),
  ]);
}

/** Wire landing-screen quick-start: one conversation CTA + tool links. */
export function bindLanding({ onStartReact, onStartConversation }) {
  const start = onStartConversation || onStartReact;
  document.querySelector('[data-action="start-conversation"]')?.addEventListener('click', start);
  // Legacy attribute kept briefly for any cached HTML; still maps to conversation.
  document.querySelector('[data-action="start-react"]')?.addEventListener('click', start);

  document.querySelector('[data-action="open-plan"]')?.addEventListener('click', () => {
    goPlan();
    import('/static/js/modules/plan.js').then(m => m.init());
  });
  document.querySelector('[data-action="open-benchmark"]')?.addEventListener('click', () => {
    goBenchmark();
    import('/static/js/modules/benchmark.js').then(m => m.init());
  });
  document.querySelector('[data-action="open-scheduler"]')?.addEventListener('click', () => {
    goScheduler();
    import('/static/js/modules/scheduler.js').then(m => m.init());
  });

  document.getElementById('btn-refresh-ws')?.addEventListener('click', () => {
    loadWorkstation();
    import('../history.js').then(m => {
      m.renderRecentLanding(document.getElementById('landing-recent'));
      m.renderSidebar();
    });
  });
}
