<script setup lang="ts">
import { computed, ref } from 'vue'
import { createTravelOrderRefund, type RefundStatus, type TravelOrder, type TravelOrderRefund } from '../api'

const props = defineProps<{ order: TravelOrder }>()

const reason = ref('')
const submitting = ref(false)
const feedback = ref('')
const refund = ref<TravelOrderRefund | null>(null)
const idempotencyKeyPrefix = 'travel-order-refund-idempotency:'

const canRequestRefund = computed(() => (
  props.order.payment_status === 'paid'
  && props.order.fulfillment_status === 'pending_confirmation'
))

function getIdempotencyKey() {
  const storageKey = `${idempotencyKeyPrefix}${props.order.id}`
  try {
    const storedKey = window.sessionStorage.getItem(storageKey)
    if (storedKey) return storedKey

    const key = crypto.randomUUID()
    window.sessionStorage.setItem(storageKey, key)
    return key
  } catch {
    return crypto.randomUUID()
  }
}

function refundStatusLabel(status: RefundStatus) {
  const labels: Record<RefundStatus, string> = {
    requested: 'Refund request received',
    processing: 'Refund processing',
    refunded: 'Refunded',
    failed: 'Refund failed',
  }
  return labels[status]
}

async function requestRefund() {
  const trimmedReason = reason.value.trim()
  if (!trimmedReason || submitting.value || !canRequestRefund.value) return

  submitting.value = true
  feedback.value = ''
  try {
    const { data } = await createTravelOrderRefund(props.order.id, {
      amount: props.order.amount,
      currency: props.order.currency,
      reason: trimmedReason,
    }, getIdempotencyKey())
    refund.value = data
  } catch {
    feedback.value = 'Refund request could not be submitted. No refund has been confirmed.'
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <section class="refund-panel" aria-label="Refund">
    <div class="refund-panel__head">
      <h2>Refund</h2>
      <p v-if="canRequestRefund">Request a refund of {{ order.currency }} {{ order.amount }} before supplier fulfillment begins.</p>
      <p v-else>Refund requests are available only for paid orders awaiting supplier fulfillment.</p>
    </div>
    <Transition name="slide-down">
      <form v-if="canRequestRefund" class="refund-form" @submit.prevent="requestRefund">
        <label class="refund-label" :for="`refund-reason-${order.id}`">Reason</label>
        <textarea
          :id="`refund-reason-${order.id}`"
          v-model="reason"
          class="refund-textarea"
          maxlength="500"
          required
          :disabled="submitting"
        />
        <button class="primary refund-submit" type="submit" :disabled="submitting || !reason.trim()">{{ submitting ? 'Submitting refund...' : 'Request refund' }}</button>
      </form>
    </Transition>
    <Transition name="slide-down">
      <p v-if="refund" :class="['refund-status', refund.status]" role="status">{{ refundStatusLabel(refund.status) }}: {{ refund.currency }} {{ refund.amount }}.</p>
    </Transition>
    <Transition name="slide-down">
      <p v-if="feedback" class="feedback" role="alert">{{ feedback }}</p>
    </Transition>
  </section>
</template>

<style scoped>
/* ============ 退款面板 ============ */
.refund-panel {
  border-top: 1px dashed var(--field-line);
  color: var(--field-muted);
  margin-top: 20px;
  padding-top: 20px;
}

.refund-panel__head { min-width: 0; }

.refund-panel h2 {
  color: var(--field-ink);
  font-size: 17px;
  font-weight: 700;
  margin: 0 0 6px;
}

.refund-panel p {
  font-size: 14px;
  line-height: 1.5;
  margin: 0;
  max-width: 55ch;
}

/* ============ 退款表单 ============ */
.refund-form {
  display: grid;
  gap: 8px;
  margin-top: 14px;
  max-width: 440px;
}

.refund-label {
  color: var(--field-ink);
  font-size: 13px;
  font-weight: 600;
}

.refund-textarea {
  background: var(--field-white);
  border: 1px solid var(--field-line);
  border-radius: var(--travel-radius-sm);
  color: var(--field-ink);
  font: inherit;
  min-height: 88px;
  padding: 10px 12px;
  resize: vertical;
  transition: border-color var(--motion-base) var(--ease-standard), box-shadow var(--motion-base) var(--ease-standard);
}

.refund-textarea:hover:not(:disabled) { border-color: color-mix(in srgb, var(--field-teal) 50%, var(--field-line)); }

.refund-textarea:focus-visible {
  border-color: var(--field-teal);
  box-shadow: 0 0 0 3px var(--field-teal-soft);
  outline: 0;
}

.refund-textarea:disabled { background: var(--field-paper); cursor: not-allowed; opacity: 0.7; }

/* ============ 退款提交按钮 ============ */
.refund-submit {
  background: var(--field-teal);
  border: 1px solid var(--field-teal);
  border-radius: var(--travel-radius-sm);
  color: var(--field-white);
  cursor: pointer;
  font-weight: 800;
  font-size: 13px;
  justify-self: start;
  min-height: 40px;
  padding: 0 15px;
  transition: background-color var(--motion-base) var(--ease-standard), border-color var(--motion-base) var(--ease-standard), color var(--motion-base) var(--ease-standard), transform var(--motion-base) var(--ease-standard), box-shadow var(--motion-base) var(--ease-standard);
}

.refund-submit:hover:not(:disabled) {
  background: var(--field-deep);
  border-color: var(--field-deep);
  transform: translateY(-1px);
}

.refund-submit:active:not(:disabled) { transform: translateY(0) scale(0.98); }

.refund-submit:disabled { cursor: wait; opacity: 0.55; }

.refund-submit:focus-visible { outline: 3px solid var(--field-saffron); outline-offset: 3px; }

/* ============ 退款状态 / 反馈 ============ */
.refund-status,
.feedback {
  margin-top: 12px;
}

.refund-status {
  font-weight: 600;
}

.refund-status.processing { color: #9c6500; }
.refund-status.refunded { color: var(--field-teal); }
.refund-status.failed,
.feedback { color: var(--field-coral); }

/* ============ 响应式 ============ */
@media (max-width: 600px) {
  .refund-submit { justify-self: stretch; width: 100%; }
}

@media (prefers-reduced-motion: reduce) {
  .refund-textarea, .refund-submit { transition: none; }
}
</style>
