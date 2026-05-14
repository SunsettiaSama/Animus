<template>
  <div class="route-skeleton" aria-busy="true" aria-label="Loading page">
    <div class="sk-line sk-title" />
    <div class="sk-line" />
    <div class="sk-line sk-short" />
  </div>
</template>

<style scoped>
.route-skeleton {
  padding: 1.25rem;
  max-width: 42rem;
}
.sk-line {
  height: 0.75rem;
  border-radius: 4px;
  background: linear-gradient(90deg, #eee 25%, #f5f5f5 50%, #eee 75%);
  background-size: 200% 100%;
  animation: pulse 1.2s ease-in-out infinite;
  margin-bottom: 0.75rem;
}
.sk-title {
  height: 1.25rem;
  width: 40%;
  margin-bottom: 1rem;
}
.sk-short {
  width: 65%;
}
@keyframes pulse {
  0% { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}
</style>
