<script setup lang="ts">
import type { FulfillmentStatus, TravelOrder } from '../api'

defineProps<{ order: TravelOrder }>()

function fulfillmentLabel(status: FulfillmentStatus) {
  const labels: Record<FulfillmentStatus, string> = {
    pending_confirmation: 'Waiting for supplier confirmation',
    confirming: 'Supplier confirmation in progress',
    confirmed: 'Supplier confirmation received',
    failed: 'Fulfillment failed',
    not_supported: 'Fulfillment unavailable',
  }
  return labels[status]
}

function fulfillmentSummary(order: TravelOrder) {
  if (order.payment_status === 'paid' && order.fulfillment_status === 'pending_confirmation') {
    return 'Payment received. Supplier confirmation is still pending.'
  }
  if (order.fulfillment_status === 'confirming') return 'Supplier confirmation is in progress.'
  if (order.fulfillment_status === 'confirmed') return 'Supplier confirmation has been received.'
  if (order.fulfillment_status === 'failed') return 'Fulfillment could not be completed.'
  if (order.fulfillment_status === 'not_supported') return 'Fulfillment is unavailable for this order.'
  return 'Fulfillment has not started.'
}

function paymentLabel(status: string) {
  if (status === 'paid') return 'Payment received'
  if (status === 'pending') return 'Payment pending'
  if (status === 'unavailable') return 'Payment unavailable'
  if (status === 'failed') return 'Payment failed'
  if (status === 'refunded') return 'Payment refunded'
  return 'Payment not started'
}

function orderStatusLabel(status: string) {
  const labels: Record<string, string> = {
    PENDING_CONFIRMATION: 'Order awaiting confirmation',
    PAYING: 'Payment in progress',
    PAID_PENDING_FULFILLMENT: 'Paid, waiting for supplier confirmation',
    CONFIRMED: 'Supplier confirmed',
    FAILED: 'Order failed',
    REFUNDING: 'Refund in progress',
    REFUNDED: 'Order refunded',
    CLOSED: 'Order closed',
  }
  return labels[status] ?? `Order status: ${status}`
}
</script>

<template>
  <article class="order-card">
    <header class="order-card__head">
      <div class="order-card__title">
        <p class="eyebrow">Platform order</p>
        <strong class="order-no">{{ order.order_no }}</strong>
      </div>
      <strong class="amount">{{ order.currency }} {{ order.amount }}</strong>
    </header>
    <div class="state-rail" aria-label="Order state">
      <p><span :class="['dot', order.payment_status]" />{{ paymentLabel(order.payment_status) }}</p>
      <p><span :class="['dot', order.fulfillment_status]" />{{ fulfillmentLabel(order.fulfillment_status) }}</p>
    </div>
    <p :class="['fulfillment-summary', order.fulfillment_status]">{{ fulfillmentSummary(order) }}</p>
    <p class="status">{{ orderStatusLabel(order.status) }}</p>
    <Transition name="slide-down">
      <p v-if="order.failure_code" class="failure-code">Failure code: {{ order.failure_code }}</p>
    </Transition>
  </article>
</template>

<style scoped>
/* ============ 订单状态卡 ============ */
.order-card {
  background: linear-gradient(135deg, color-mix(in srgb, var(--field-teal-soft) 62%, var(--field-white)), var(--field-white) 58%);
  border: 1px solid var(--field-line);
  border-radius: var(--travel-radius);
  color: var(--field-ink);
  padding: 18px;
}

.order-card__head {
  align-items: flex-start;
  border-bottom: 1px solid var(--field-line);
  display: flex;
  gap: 16px;
  justify-content: space-between;
  padding-bottom: 16px;
}

.order-card__title { min-width: 0; }

.eyebrow {
  background: var(--field-white);
  border: 1px solid var(--field-line);
  border-radius: 999px;
  color: var(--field-ink-soft);
  display: inline-block;
  font: 600 12px var(--field-mono);
  margin: 0 0 6px;
  padding: 3px 8px;
  text-transform: uppercase;
}

.order-no {
  color: var(--field-ink);
  display: block;
  font-size: 15px;
  font-weight: 700;
  letter-spacing: 0.01em;
}

.amount {
  color: var(--field-deep);
  font-size: 19px;
  font-weight: 700;
  white-space: nowrap;
}

/* ============ 状态轨 ============ */
.state-rail {
  border-left: 2px solid var(--field-saffron);
  display: grid;
  gap: 10px;
  margin: 20px 0 12px 7px;
  padding-left: 16px;
}

.state-rail p {
  align-items: center;
  color: var(--field-ink);
  display: flex;
  font-size: 13px;
  font-weight: 600;
  margin: 0;
}

.dot {
  background: var(--field-muted);
  border-radius: 50%;
  box-shadow: 0 0 0 3px var(--field-white);
  display: inline-block;
  flex-shrink: 0;
  height: 9px;
  margin-left: -22px;
  margin-right: 13px;
  width: 9px;
}

.dot.paid,
.dot.confirmed { background: var(--field-teal); }
.dot.pending,
.dot.pending_confirmation { background: var(--field-coral); }

/* ============ 履约摘要 / 状态 / 失败码 ============ */
.fulfillment-summary {
  background: var(--field-white);
  border-left: 3px solid var(--field-teal);
  border-radius: 0 var(--travel-radius-sm) var(--travel-radius-sm) 0;
  color: var(--field-ink);
  font-weight: 600;
  margin: 0;
  padding: 10px 12px;
}

.fulfillment-summary.pending_confirmation,
.fulfillment-summary.confirming { color: #9c6500; }
.fulfillment-summary.failed,
.fulfillment-summary.not_supported { color: #9c4234; }

.status {
  color: var(--field-ink-soft);
  font-size: 13px;
  margin: 8px 0 0;
}

.failure-code {
  color: var(--field-coral);
  font-family: var(--field-mono);
  font-size: 12px;
  margin: 8px 0 0;
}

/* ============ 响应式 ============ */
@media (max-width: 500px) {
  .order-card__head { flex-direction: column; gap: 6px; }
  .amount { font-size: 17px; }
}

@media (prefers-reduced-motion: reduce) {
  .fulfillment-summary, .status, .failure-code { transition: none; }
}
</style>
