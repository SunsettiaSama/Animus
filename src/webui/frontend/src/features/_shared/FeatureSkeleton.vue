<script setup>
defineProps({
  title: { type: String, default: 'Screen' },
  hint: { type: String, default: '' },
});
</script>

<template>
  <section class="feature-skeleton">
    <h1>{{ title }}</h1>
    <p class="hint">{{ hint }}</p>
    <p class="note">
      Feature scaffold — wire API via <code>@/api</code> (re-exports <code>static/js/api.js</code>).
    </p>
  </section>
</template>

<style scoped>
.feature-skeleton { padding: 1.25rem; max-width: 42rem; }
h1 { font-size: 1.25rem; margin: 0 0 0.5rem; }
.hint { color: #555; margin: 0 0 0.75rem; }
.note { font-size: 0.85rem; color: #666; }
code { font-size: 0.85em; background: #f2f2f2; padding: 0.1em 0.35em; border-radius: 4px; }
</style>
