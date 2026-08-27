<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { RefreshCw } from 'lucide-vue-next'
import { useRoute, useRouter } from 'vue-router'
import { useReveal } from '@/composables/useReveal'

const root = ref<HTMLElement | null>(null)
useReveal(root)

const route = useRoute()
const router = useRouter()

onMounted(() => {
  const purchaseId = typeof route.params.purchaseId === 'string' ? route.params.purchaseId : ''
  void router.replace(purchaseId ? `/memberships/pay/${purchaseId}` : '/memberships')
})
</script>

<template>
  <main class="return-page" aria-busy="true" aria-live="polite" ref="root">
    <div class="return-card reveal">
      <RefreshCw class="spin" :size="28" />
      <p class="eyebrow">会员购买</p>
      <h1>正在恢复会员支付状态...</h1>
      <p class="return-card__lead">即将跳转至支付页面，请稍候。</p>
    </div>
  </main>
</template>

<style scoped>
.return-page {
  color: var(--field-ink);
  display: flex;
  justify-content: center;
  margin: auto;
  max-width: 700px;
  padding: 80px 24px;
  position: relative;
}

.return-card {
  align-items: center;
  background: var(--field-white);
  border: 1px solid var(--field-line);
  border-radius: var(--travel-radius);
  display: grid;
  gap: 14px;
  justify-items: center;
  padding: 56px 28px;
  text-align: center;
  width: 100%;
  position: relative;
  overflow: hidden;
}

.return-card::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 4px;
  background: linear-gradient(90deg, var(--field-teal), var(--field-coral), var(--field-saffron));
}

.return-card::after {
  content: '';
  position: absolute;
  inset: 0;
  background: radial-gradient(circle at center top, rgba(8, 126, 120, 0.04), transparent 70%);
  pointer-events: none;
}

.return-card svg {
  color: var(--field-teal);
  position: relative;
  z-index: 1;
}

.eyebrow {
  color: var(--field-teal);
  font: 800 11px var(--field-mono);
  letter-spacing: 0.12em;
  text-transform: uppercase;
  margin: 0;
  position: relative;
  z-index: 1;
}

.return-card h1 {
  font-family: Georgia, "Noto Serif SC", serif;
  font-size: 24px;
  font-weight: 600;
  line-height: 1.3;
  margin: 0;
  position: relative;
  z-index: 1;
}

.return-card__lead {
  color: var(--field-muted);
  font-size: 13px;
  margin: 0;
  position: relative;
  z-index: 1;
}

.reveal {
  animation: reveal-up var(--motion-slow) var(--ease-out) both;
}

@keyframes reveal-up {
  from { opacity: 0; transform: translateY(16px) scale(0.97); }
  to { opacity: 1; transform: translateY(0) scale(1); }
}

@media (max-width: 700px) {
  .return-page { padding: 48px 16px; }
  .return-card { padding: 40px 20px; }
}

@media (prefers-reduced-motion: reduce) {
  .reveal { animation: none; }
  .spin { animation: none; }
}
</style>
