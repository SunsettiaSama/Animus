import { createRouter, createWebHashHistory } from 'vue-router';
import { routes } from './routes.js';

export function createAppRouter() {
  return createRouter({
    history: createWebHashHistory(),
    routes,
  });
}
