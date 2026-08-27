<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { fetchTravelOrders, queryTravelOrderPayment, type TravelOrder } from '../api'
import { useReveal } from '@/composables/useReveal'

const state = ref<'checking' | 'complete' | 'unavailable'>('checking')
const message = ref('正在向订单服务核对支付结果。')
const root = ref<HTMLElement | null>(null)
useReveal(root)

onMounted(async () => {
  try {
    const { data: orders } = await fetchTravelOrders()
    const unresolved = orders.filter((order: TravelOrder) => order.status === 'PAYING' && order.payment_status === 'paying')
    const results = await Promise.all(unresolved.map((order: TravelOrder) => queryTravelOrderPayment(order.id)))
    state.value = 'complete'
    message.value = results.some(({ data }) => data.payment_status === 'paid')
      ? '支付结果已向订单服务核对。支付成功后，订单仍需等待供应商确认。'
      : '订单仍在等待支付确认。请稍后在订单页刷新支付状态。'
  } catch {
    state.value = 'unavailable'
    message.value = '暂时无法核对支付结果。请稍后在订单页刷新支付状态。'
  }
})
</script>

<template>
  <main class="payment-return" ref="root">
    <div class="payment-return__inner" data-reveal>
      <p>PAYMENT RETURN</p>
      <h1>{{ state === 'checking' ? '正在核对支付结果' : state === 'complete' ? '支付结果已核对' : '支付结果暂未确认' }}</h1>
      <span>{{ message }}</span>
      <RouterLink class="payment-return__link" to="/me/orders">返回订单</RouterLink>
    </div>
  </main>
</template>

<style scoped>
/* ============ 页面容器 ============ */
.payment-return {
  color: var(--field-ink);
  margin: 0 auto;
  max-width: 720px;
  padding: 56px 24px 80px;
}

.payment-return__inner {
  background: var(--field-white);
  border: 1px solid var(--field-line);
  border-radius: var(--travel-radius);
  box-shadow: var(--shadow-lift);
  padding: 48px;
  position: relative;
}

.payment-return__inner::before {
  background: var(--field-saffron);
  border-radius: 50%;
  content: '';
  height: 12px;
  left: 48px;
  position: absolute;
  top: 30px;
  width: 12px;
}

.payment-return p {
  color: var(--field-teal);
  font: 800 11px var(--field-mono);
  letter-spacing: 0.09em;
  margin: 0 0 12px 22px;
}

.payment-return h1 {
  font-size: 36px;
  letter-spacing: 0;
  line-height: 1.18;
  margin: 0 0 12px;
}

.payment-return span {
  color: var(--field-muted);
  display: block;
  font-size: 15px;
  line-height: 1.6;
  max-width: 42ch;
}

/* ============ 返回链接 ============ */
.payment-return__link {
  background: var(--field-teal);
  border-radius: var(--travel-radius-sm);
  color: var(--field-white);
  display: inline-block;
  font-weight: 800;
  font-size: 14px;
  margin-top: 25px;
  padding: 12px 18px;
  text-decoration: none;
  transition: background-color var(--motion-base) var(--ease-standard), transform var(--motion-base) var(--ease-standard), box-shadow var(--motion-base) var(--ease-standard);
}

.payment-return__link:hover {
  background: var(--field-deep);
  box-shadow: var(--shadow-soft);
  transform: translateY(-1px);
}

.payment-return__link:active { transform: translateY(0) scale(0.98); }

.payment-return__link:focus-visible { outline: 3px solid var(--field-saffron); outline-offset: 3px; }

/* ============ 响应式 ============ */
@media (max-width: 600px) {
  .payment-return { margin: 28px 16px; padding: 0 0 56px; }
  .payment-return__inner { padding: 38px 24px; }
  .payment-return__inner::before { left: 24px; }
  .payment-return h1 { font-size: 29px; }
  .payment-return p { margin-left: 22px; }
}

@media (prefers-reduced-motion: reduce) {
  .payment-return__link { transition: none; }
}
</style>
