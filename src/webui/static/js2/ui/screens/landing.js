/**
 * ui/screens/landing.js — 工作站（Landing）屏幕。
 */

import { bus, EVENTS } from '../../store/bus.js';
import { goPlan, goBenchmark, goScheduler } from '../router.js';
import * as cards from './workstation_cards.js';
import * as historyStore from '../../store/history_store.js';

/** 刷新所有工作站摘要卡片。 */
export async function loadWorkstation() {
  await cards.refreshAll();
}

/**
 * 绑定 Landing 快速入口：单会话 CTA + 工具链接 + 刷新。
 */
export function bindLanding({ onStartConversation }) {
  document.querySelector('[data-action="start-conversation"]')?.addEventListener('click', onStartConversation);
  // 兼容缓存 HTML 中的旧属性
  document.querySelector('[data-action="start-react"]')?.addEventListener('click', onStartConversation);

  document.querySelector('[data-action="open-plan"]')?.addEventListener('click', () => {
    goPlan();
    import('../../features/plan_bridge.js').then(m => m.init()).catch(() => {});
  });
  document.querySelector('[data-action="open-benchmark"]')?.addEventListener('click', () => {
    goBenchmark();
    import('../../features/bench_bridge.js').then(m => m.init()).catch(() => {});
  });
  document.querySelector('[data-action="open-scheduler"]')?.addEventListener('click', () => {
    goScheduler();
    import('../../features/scheduler_bridge.js').then(m => m.init()).catch(() => {});
  });

  document.getElementById('btn-refresh-ws')?.addEventListener('click', () => {
    loadWorkstation();
    historyStore.refreshList().catch(() => {});
  });

  // 卡片 soul 动作（Setup/Init/Build）由 app 装配时订阅
}
