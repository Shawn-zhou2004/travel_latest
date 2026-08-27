<script setup lang="ts">
import { RouterLink } from 'vue-router'
</script>

<template>
  <main class="access-page">
    <p class="eyebrow">需要登录</p>
    <h1>这一页只对已登录的旅行者开放。</h1>
    <p>打开你的会话，继续查看已保存的行程、对话与订单。</p>
    <RouterLink class="action" :to="{ path: '/login', query: { redirect: '/itineraries' } }">前往登录</RouterLink>
  </main>
</template>

<style scoped>
.access-page {
  animation: access-enter var(--motion-slow) var(--ease-out) both;
  background: var(--field-white);
  border: 1px solid var(--field-line);
  border-left: 5px solid var(--field-saffron);
  border-radius: 12px;
  box-shadow: 0 18px 44px color-mix(in srgb, var(--field-deep) 9%, transparent);
  color: var(--field-ink);
  margin: 64px auto;
  max-width: 680px;
  padding: 48px;
}
@keyframes access-enter { from { opacity: 0; transform: translateY(14px); } to { opacity: 1; transform: translateY(0); } }
.eyebrow {
  background: var(--field-teal-soft);
  border-radius: 999px;
  color: var(--field-teal);
  display: inline-block;
  font: 700 12px var(--field-mono);
  letter-spacing: .04em;
  padding: 5px 9px;
  text-transform: uppercase;
}
.access-page h1 { font-size: 38px; letter-spacing: 0; line-height: 1.15; margin: 18px 0 12px; }
.access-page p { color: var(--field-muted); font-size: 15px; line-height: 1.7; max-width: 44ch; }
.action {
  background: var(--field-deep);
  border-radius: 7px;
  box-shadow: 0 8px 16px color-mix(in srgb, var(--field-deep) 18%, transparent);
  color: var(--field-white);
  display: inline-block;
  font-weight: 800;
  margin-top: 18px;
  padding: 12px 18px;
  text-decoration: none;
  transition: background-color var(--motion-base) var(--ease-standard), transform var(--motion-base) var(--ease-standard), box-shadow var(--motion-base) var(--ease-standard);
}
.action:hover { background: var(--field-teal); transform: translateY(-2px); box-shadow: 0 12px 22px color-mix(in srgb, var(--field-teal) 26%, transparent); }
.action:active { transform: translateY(0) scale(0.98); }
.action:focus-visible { outline: 3px solid var(--field-saffron); outline-offset: 3px; }
@media (max-width: 600px) {
  .access-page { margin: 28px 16px; padding: 32px 24px; }
  .access-page h1 { font-size: 30px; }
}
@media (prefers-reduced-motion: reduce) {
  .access-page { animation: none; }
  .action { transition: none; transform: none; }
}
</style>
