/** Aligns with static/js/router.js SCREENS order; lazy chunks per feature. */
export const routes = [
  { path: '/', name: 'landing', component: () => import('@/features/landing/LandingView.vue'), meta: { legacyScreenId: 's-landing' } },
  { path: '/workspace', name: 'workspace', component: () => import('@/features/workspace/WorkspaceView.vue'), meta: { legacyScreenId: 's-workspace' } },
  { path: '/plan', name: 'plan', component: () => import('@/features/plan/PlanView.vue'), meta: { legacyScreenId: 's-plan' } },
  { path: '/benchmark', name: 'benchmark', component: () => import('@/features/benchmark/BenchmarkView.vue'), meta: { legacyScreenId: 's-benchmark' } },
  { path: '/scheduler', name: 'scheduler', component: () => import('@/features/scheduler/SchedulerView.vue'), meta: { legacyScreenId: 's-scheduler' } },
  { path: '/settings', name: 'settings', component: () => import('@/features/settings/SettingsView.vue'), meta: { legacyScreenId: null } },
];
