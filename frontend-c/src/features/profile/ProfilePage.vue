<script setup lang="ts">
import { ref } from 'vue'
import { Settings } from 'lucide-vue-next'
import { useReveal } from '@/composables/useReveal'

const root = ref<HTMLElement | null>(null)
useReveal(root)
</script>

<template>
  <main class="profile-compat" aria-label="账户资料迁移提示" ref="root">
    <div class="profile-card" data-reveal>
      <h1>账户资料已迁移</h1>
      <p>请在个人设置中管理显示名称、头像和隐私偏好。</p>
      <a href="/me/settings#profile"><Settings :size="17" />前往个人设置</a>
    </div>
  </main>
</template>

<style scoped>
.profile-compat {
  color: var(--field-ink);
  margin: 0 auto;
  max-width: 720px;
  min-height: calc(100vh - 70px);
  padding: 72px 24px;
}

.profile-card {
  animation: header-enter var(--motion-slow) var(--ease-out) both;
}

@keyframes header-enter {
  from { opacity: 0; transform: translateY(-10px); }
  to { opacity: 1; transform: translateY(0); }
}

.profile-compat h1 {
  font-size: 30px;
  line-height: 1.15;
  margin: 0;
}

.profile-compat p {
  color: var(--field-muted);
  margin: 12px 0 24px;
}

.profile-compat a {
  align-items: center;
  background: var(--field-deep);
  border-radius: 6px;
  color: var(--field-white);
  display: inline-flex;
  font-size: 14px;
  font-weight: 800;
  gap: 8px;
  min-height: 42px;
  padding: 0 14px;
  text-decoration: none;
  transition: background-color var(--motion-base) var(--ease-standard), transform var(--motion-base) var(--ease-standard), box-shadow var(--motion-base) var(--ease-standard);
}

.profile-compat a:hover {
  background: var(--field-teal);
  transform: translateY(-1px);
  box-shadow: var(--shadow-soft);
}

.profile-compat a:active { transform: translateY(0) scale(0.98); }

.profile-compat a:focus-visible {
  outline: 3px solid var(--field-saffron);
  outline-offset: 3px;
}

@media (prefers-reduced-motion: reduce) {
  .profile-card { animation: none; }
  .profile-compat a { transition: none; }
  .profile-compat a:hover { transform: none; }
}
</style>
