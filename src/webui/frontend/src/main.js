import { createApp } from 'vue';
import { createPinia } from 'pinia';
import App from './App.vue';
import { appBus } from './bus/appBus.js';
import { EVENTS } from './events.js';
import { createAppRouter } from './router/index.js';

const app = createApp(App);
const pinia = createPinia();
const router = createAppRouter();

router.afterEach((to) => {
  const legacy = to.meta?.legacyScreenId;
  if (legacy) appBus.emit(EVENTS.screenEnter, legacy);
  appBus.emit(EVENTS.navigate, to.meta?.legacyScreenId ?? to.name);
});

app.use(pinia);
app.use(router);
app.mount('#app');
