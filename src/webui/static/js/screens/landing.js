/**
 * screens/landing.js — Workstation / Landing screen logic.
 *
 * Responsibilities:
 *   - Refresh all module workstation cards.
 *   - Render the "recent conversations" list.
 *   - Wire quick-start card click handlers.
 */

import { http, PATHS }         from '../api.js';
import { bus }                 from '../eventBus.js';
import { goWorkspace, goPlan,
         goBenchmark, goScheduler } from '../router.js';

let _modules = null;   // injected by app.js to avoid circular deps

/**
 * Provide module references needed for workstation card updates.
 * Called from app.js during boot.
 */
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

/** Wire landing-screen quick-start cards and the refresh button. */
export function bindLanding({ onStartReact }) {
  document.querySelector('[data-action="start-react"]')?.addEventListener('click', onStartReact);
  document.querySelector('[data-action="start-plan"]')?.addEventListener('click', () => {
    goPlan();
    import('/static/js/modules/plan.js').then(m => m.init());
  });
  document.querySelector('[data-action="start-benchmark"]')?.addEventListener('click', () => {
    goBenchmark();
    import('/static/js/screens/benchmark.js').then(m => m.init()).catch(() =>
      import('/static/js/modules/benchmark.js').then(m => m.init()));
  });
  document.querySelector('[data-action="start-scheduler"]')?.addEventListener('click', () => {
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
