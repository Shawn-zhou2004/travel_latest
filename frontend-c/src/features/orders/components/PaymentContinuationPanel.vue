<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { createTravelOrderPayment, queryTravelOrderPayment, type TravelOrder } from '../api'
import { newClientId } from '@/services/id'

const props = defineProps<{ order: TravelOrder }>()
const emit = defineEmits<{ updated: [order: TravelOrder] }>()

const creating = ref(false)
const refreshing = ref(false)
const feedback = ref('')
const idempotencyKeyPrefix = 'travel-order-payment-idempotency:'

const canStartPayment = computed(() => (
  ['PENDING_CONFIRMATION', 'PAYING'].includes(props.order.status)
  && ['pending', 'paying'].includes(props.order.payment_status)
))

async function refreshPayment(showFeedback: boolean) {
  refreshing.value = true
  try {
    const { data } = await queryTravelOrderPayment(props.order.id)
    emit('updated', data)
    if (showFeedback) {
      feedback.value = data.failure_code === 'PAYMENT_NOT_CONFIGURED'
        ? 'Online payment is not configured. No payment was submitted.'
        : 'Payment status refreshed from the order service.'
    }
  } catch {
    if (showFeedback) feedback.value = 'Payment status could not be refreshed. Try again shortly.'
  } finally {
    refreshing.value = false
  }
}

function refreshPaymentFromButton() {
  return refreshPayment(true)
}

function getIdempotencyKey() {
  const storageKey = `${idempotencyKeyPrefix}${props.order.id}`
  try {
    const storedKey = window.sessionStorage.getItem(storageKey)
    if (storedKey) return storedKey

    const key = newClientId()
    window.sessionStorage.setItem(storageKey, key)
    return key
  } catch {
    return newClientId()
  }
}

function isHttpsRedirectUrl(value: string | null): value is string {
  if (!value) return false
  try {
    return new URL(value).protocol === 'https:'
  } catch {
    return false
  }
}

function paymentErrorMessage(reason: unknown) {
  const code = typeof reason === 'object' && reason !== null && 'code' in reason
    ? (reason as { code?: unknown }).code
    : undefined
  return code === 'PAYMENT_NOT_CONFIGURED'
    ? 'Online payment is unavailable for this order. No payment was submitted.'
    : 'Payment could not be started. Checking the latest order status.'
}

async function startPayment() {
  creating.value = true
  feedback.value = ''
  try {
    const { data } = await createTravelOrderPayment(props.order.id, getIdempotencyKey())
    if (!isHttpsRedirectUrl(data.redirect_url)) {
      feedback.value = 'The payment provider did not provide a secure checkout link. No payment was confirmed.'
      return
    }

    window.location.assign(data.redirect_url)
  } catch (reason) {
    feedback.value = paymentErrorMessage(reason)
  } finally {
    creating.value = false
    await refreshPayment(false)
  }
}

function refreshAfterReturn() {
  void refreshPayment(false)
}

onMounted(() => {
  void refreshPayment(false)
  window.addEventListener('pageshow', refreshAfterReturn)
})

onBeforeUnmount(() => {
  window.removeEventListener('pageshow', refreshAfterReturn)
})
</script>

<template>
  <section class="payment-panel" aria-label="Payment">
    <div class="payment-panel__body">
      <h2>Payment</h2>
      <p v-if="order.failure_code === 'PAYMENT_NOT_CONFIGURED'" class="unavailable">Online payment is unavailable for this order. No payment was submitted.</p>
      <p v-else-if="canStartPayment">Start checkout only when you are ready to continue with {{ order.currency }} {{ order.amount }}.</p>
      <p v-else>Payment actions are unavailable for the current order state.</p>
      <Transition name="slide-down">
        <p v-if="feedback" class="feedback" role="status">{{ feedback }}</p>
      </Transition>
    </div>
    <div class="actions">
      <Transition name="fade">
        <button v-if="canStartPayment" class="primary" type="button" :disabled="creating || refreshing" @click="startPayment">{{ creating ? 'Starting checkout...' : 'Continue to payment' }}</button>
      </Transition>
      <button class="secondary" type="button" :disabled="creating || refreshing" @click="refreshPaymentFromButton">{{ refreshing ? 'Refreshing...' : 'Refresh payment status' }}</button>
    </div>
  </section>
</template>

<style scoped>
/* ============ 支付面板 ============ */
.payment-panel {
  align-items: center;
  border-top: 1px dashed var(--field-line);
  display: flex;
  gap: 20px;
  justify-content: space-between;
  margin-top: 20px;
  padding-top: 20px;
}

.payment-panel__body { min-width: 0; }

.payment-panel h2 {
  color: var(--field-ink);
  font-size: 17px;
  font-weight: 700;
  margin: 0 0 6px;
}

.payment-panel p {
  color: var(--field-muted);
  font-size: 14px;
  line-height: 1.5;
  margin: 0;
  max-width: 49ch;
}

.unavailable {
  color: var(--field-coral);
  font-weight: 600;
}

.feedback {
  color: var(--field-ink-soft);
  margin-top: 10px;
}

/* ============ 操作按钮 ============ */
.actions {
  align-items: center;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: flex-end;
}

.actions button {
  border: 1px solid var(--field-teal);
  border-radius: var(--travel-radius-sm);
  cursor: pointer;
  font-weight: 800;
  font-size: 13px;
  min-height: 40px;
  padding: 0 14px;
  transition: background-color var(--motion-base) var(--ease-standard), border-color var(--motion-base) var(--ease-standard), color var(--motion-base) var(--ease-standard), transform var(--motion-base) var(--ease-standard), box-shadow var(--motion-base) var(--ease-standard);
  white-space: nowrap;
}

.primary {
  background: var(--field-teal);
  box-shadow: 0 7px 14px color-mix(in srgb, var(--field-teal) 22%, transparent);
  color: var(--field-white);
}

.secondary {
  background: transparent;
  color: var(--field-teal);
}

.actions button:hover:not(:disabled) {
  background: var(--field-deep);
  border-color: var(--field-deep);
  color: var(--field-white);
  transform: translateY(-1px);
}

.actions button:active:not(:disabled) { transform: translateY(0) scale(0.98); }

.actions button:disabled { cursor: wait; opacity: 0.55; }

.actions button:focus-visible { outline: 3px solid var(--field-saffron); outline-offset: 3px; }

/* ============ 响应式 ============ */
@media (max-width: 600px) {
  .payment-panel { align-items: stretch; flex-direction: column; }
  .actions { justify-content: stretch; }
  .actions button { flex: 1; }
}

@media (prefers-reduced-motion: reduce) {
  .actions button { transition: none; }
}
</style>
