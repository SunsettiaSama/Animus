/**
 * ui/screens/landing.js — 工作站（Landing）屏幕。
 */

import { goPlan, goBenchmark, goScheduler } from '../router.js';
import * as cards from './workstation_cards.js';

/** 刷新所有工作站摘要卡片。 */
export async function loadWorkstation() {
  await cards.refreshAll();
}

/**
 * 绑定 Landing 快速入口：工具链接 + 刷新。
 * 单窗口：无"新对话"入口——对话流即唯一表面，历史走时间轴/回忆。
 */
export function bindLanding() {
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
  });

  // 卡片 soul 动作（Setup/Init/Build）由 app 装配时订阅
}
