<script setup>
import RouteSkeleton from '@/shared/skeletons/RouteSkeleton.vue';
import { EVENTS } from './events.js';
import { appBus } from './bus/appBus.js';

function onToast(msg) {
  const el = document.getElementById('vue-toast');
  if (!el) return;
  el.textContent = msg;
  el.classList.add('show');
  setTimeout(() => el.classList.remove('show'), 2500);
}
appBus.on(EVENTS.toast, onToast);
</script>

<template>
  <div class="vue-app">
    <header class="top">
      <strong>ReAct · Vue shell</strong>
      <nav>
        <router-link to="/">Landing</router-link>
        <router-link to="/workspace">Workspace</router-link>
        <router-link to="/plan">Plan</router-link>
        <router-link to="/benchmark">Benchmark</router-link>
        <router-link to="/scheduler">Scheduler</router-link>
        <router-link to="/settings">Settings</router-link>
      </nav>
    </header>
    <main class="shell-main">
      <router-view v-slot="{ Component }">
        <template v-if="Component">
          <Suspense>
            <component :is="Component" />
            <template #fallback>
              <RouteSkeleton />
            </template>
          </Suspense>
        </template>
      </router-view>
    </main>
    <div id="vue-toast" class="toast" aria-live="polite" />
  </div>
</template>

<style>
.vue-app { font-family: system-ui, sans-serif; min-height: 100vh; display: flex; flex-direction: column; }
.top {
  display: flex; align-items: center; gap: 1rem;
  flex-shrink: 0;
  padding: 0.6rem 1rem; border-bottom: 1px solid #e5e5e5; background: #fafafa;
}
.shell-main { flex: 1; min-height: 0; }
nav { display: flex; flex-wrap: wrap; gap: 0.75rem; }
nav a { color: #2563eb; text-decoration: none; font-size: 0.9rem; }
nav a.router-link-active { font-weight: 600; text-decoration: underline; }
.toast {
  position: fixed; bottom: 1rem; right: 1rem; padding: 0.5rem 0.75rem;
  background: #111; color: #fff; border-radius: 6px; font-size: 0.85rem;
  opacity: 0; pointer-events: none; transition: opacity 0.2s;
}
.toast.show { opacity: 1; }
</style>
