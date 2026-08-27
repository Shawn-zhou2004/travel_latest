<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { fetchTravelOrders, type TravelOrder } from '../api'
import OrderStateCard from '../components/OrderStateCard.vue'
import MockTicketStatePanel from '../components/MockTicketStatePanel.vue'
import PaymentContinuationPanel from '../components/PaymentContinuationPanel.vue'
import RefundRequestPanel from '../components/RefundRequestPanel.vue'
import { useReveal } from '@/composables/useReveal'

const orders = ref<TravelOrder[]>([])
const loading = ref(true)
const error = ref('')
const root = ref<HTMLElement | null>(null)
useReveal(root)

async function loadOrders() {
  loading.value = true
  error.value = ''
  try {
    orders.value = (await fetchTravelOrders()).data
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : 'Orders could not be loaded.'
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  void loadOrders()
})

function updateOrder(updatedOrder: TravelOrder) {
  orders.value = orders.value.map((order) => order.id === updatedOrder.id ? updatedOrder : order)
}
</script>

<template>
  <main class="orders" ref="root">
    <header class="orders-header" data-reveal>
      <div class="orders-header__intro">
        <p class="eyebrow">My travel</p>
        <h1>Orders and supplier status</h1>
      </div>
      <button class="refresh-orders" type="button" :disabled="loading" @click="loadOrders">{{ loading ? 'Refreshing...' : 'Refresh orders' }}</button>
    </header>
    <p v-if="loading" class="state state--loading" role="status" aria-live="polite">Loading orders...</p>
    <p v-else-if="error" class="error" role="alert">{{ error }}</p>
    <section v-else-if="orders.length" class="order-list">
      <article v-for="order in orders" :key="order.id" class="order-entry reveal">
        <OrderStateCard :order="order" />
        <MockTicketStatePanel :order="order" />
        <PaymentContinuationPanel :order="order" @updated="updateOrder" />
        <RefundRequestPanel :order="order" />
      </article>
    </section>
    <section v-else class="empty reveal">
      <strong>No platform orders yet</strong>
      <p>Offers only become orders when you select a valid supplier snapshot.</p>
    </section>
  </main>
</template>

<style scoped>
/* ============ 页面容器 ============ */
.orders {
  color: var(--field-ink);
  margin: 0 auto;
  max-width: 980px;
  padding: 44px 24px 80px;
  position: relative;
}

.orders ::-webkit-scrollbar { width: 6px; }
.orders ::-webkit-scrollbar-track { background: transparent; }
.orders ::-webkit-scrollbar-thumb { background: var(--field-line); border-radius: 3px; transition: background var(--motion-fast) var(--ease-standard); }
.orders ::-webkit-scrollbar-thumb:hover { background: var(--field-teal); }

/* ============ 页头 ============ */
.orders-header {
  align-items: flex-end;
  border-bottom: 2px solid var(--field-ink);
  display: flex;
  gap: 16px;
  justify-content: space-between;
  padding-bottom: 18px;
}

.orders-header__intro { min-width: 0; }

.eyebrow {
  background: var(--field-teal-soft);
  border-radius: 999px;
  color: var(--field-teal);
  display: inline-block;
  font: 700 12px var(--field-mono);
  letter-spacing: 0.06em;
  margin: 0 0 8px;
  padding: 5px 10px;
  text-transform: uppercase;
}

.orders h1 {
  font-size: 36px;
  letter-spacing: 0;
  line-height: 1.12;
  margin: 0;
}

/* ============ 刷新按钮 ============ */
.refresh-orders {
  background: transparent;
  border: 1px solid var(--field-teal);
  border-radius: var(--travel-radius-sm);
  color: var(--field-teal);
  cursor: pointer;
  flex: 0 0 auto;
  font-weight: 800;
  font-size: 13px;
  min-height: 42px;
  padding: 0 16px;
  transition: background-color var(--motion-base) var(--ease-standard), border-color var(--motion-base) var(--ease-standard), color var(--motion-base) var(--ease-standard), transform var(--motion-base) var(--ease-standard), box-shadow var(--motion-base) var(--ease-standard);
}

.refresh-orders:hover:not(:disabled) {
  background: var(--field-deep);
  border-color: var(--field-deep);
  color: var(--field-white);
  transform: translateY(-1px);
}

.refresh-orders:active:not(:disabled) { transform: translateY(0) scale(0.98); }

.refresh-orders:disabled { cursor: wait; opacity: 0.55; }

.refresh-orders:focus-visible { outline: 3px solid var(--field-saffron); outline-offset: 3px; }

/* ============ 状态条 ============ */
.state {
  color: var(--field-ink-soft);
  margin: 20px 0 0;
}

.state--loading {
  align-items: center;
  display: flex;
  gap: 8px;
}

.error {
  background: var(--field-white);
  border-left: 3px solid var(--field-coral);
  border-radius: 0 var(--travel-radius-sm) var(--travel-radius-sm) 0;
  color: #9c4234;
  margin: 20px 0 0;
  padding: 14px 16px;
}

/* ============ 订单列表 ============ */
.order-list {
  display: grid;
  gap: 20px;
  margin-top: 28px;
}

.order-entry {
  background: var(--field-white);
  border: 1px solid var(--field-line);
  border-radius: var(--travel-radius);
  box-shadow: var(--shadow-soft);
  padding: 22px;
  position: relative;
}

/* 抹平子卡片边框，避免卡片嵌套卡片 */
.order-entry :deep(.order-card) {
  border: 0;
  border-radius: 0;
  padding: 0;
}

.order-entry:nth-child(1) { --reveal-index: 0; }
.order-entry:nth-child(2) { --reveal-index: 1; }
.order-entry:nth-child(3) { --reveal-index: 2; }
.order-entry:nth-child(4) { --reveal-index: 3; }
.order-entry:nth-child(n+5) { --reveal-index: 4; }

/* ============ 空态 ============ */
.empty {
  background: var(--field-paper);
  border: 1px dashed var(--field-line);
  border-radius: var(--travel-radius-sm);
  color: var(--field-ink-soft);
  margin-top: 28px;
  padding: 26px;
}

.empty strong {
  color: var(--field-ink);
  display: block;
  font-size: 15px;
  margin-bottom: 6px;
}

.empty p {
  color: var(--field-muted);
  line-height: 1.6;
  margin: 0;
}

/* ============ 响应式 ============ */
@media (max-width: 500px) {
  .orders { padding: 28px 16px 56px; }
  .orders-header { align-items: stretch; flex-direction: column; gap: 12px; }
  .refresh-orders { width: 100%; }
  .orders h1 { font-size: 29px; }
  .order-entry { padding: 16px; }
  .empty { padding: 20px; }
}

@media (prefers-reduced-motion: reduce) {
  .order-entry, .empty { animation: none; }
  .refresh-orders { transition: none; }
}
</style>
