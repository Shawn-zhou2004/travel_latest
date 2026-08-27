<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { fetchMockTransportTicket, type MockTransportTicket, type TravelOrder } from '../api'

const props = defineProps<{ order: TravelOrder }>()

const ticket = ref<MockTransportTicket | null>(null)
const loading = ref(false)
const error = ref('')

function ticketStatusLabel(status: MockTransportTicket['status']) {
  return { pending: '模拟出票等待中', issued: '模拟票已出票', failed: '模拟出票失败' }[status]
}

async function loadTicket() {
  loading.value = true
  error.value = ''
  try {
    ticket.value = (await fetchMockTransportTicket(props.order.id)).data
  } catch {
    ticket.value = null
    error.value = '模拟票状态暂时无法查询。'
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  void loadTicket()
})
</script>

<template>
  <Transition name="fade">
    <section v-if="ticket || loading" class="ticket-panel" aria-label="模拟票务状态">
      <div class="ticket-panel__body">
        <h2>模拟票务状态</h2>
        <p v-if="loading" class="ticket-loading">正在查询模拟票状态...</p>
        <template v-else-if="ticket">
          <strong :class="['ticket-status', ticket.status]">{{ ticketStatusLabel(ticket.status) }}</strong>
          <p v-if="ticket.mock_ticket_no">模拟票号：{{ ticket.mock_ticket_no }}</p>
          <p v-if="ticket.failure_code" class="failure">失败原因：{{ ticket.failure_code }}</p>
        </template>
        <p v-else class="unavailable">{{ error }}</p>
      </div>
      <button class="ticket-refresh" type="button" :disabled="loading" @click="loadTicket">{{ loading ? '查询中...' : '刷新票务状态' }}</button>
    </section>
  </Transition>
</template>

<style scoped>
/* ============ 票务面板 ============ */
.ticket-panel {
  align-items: center;
  border-top: 1px dashed var(--field-line);
  display: flex;
  gap: 16px;
  justify-content: space-between;
  margin-top: 20px;
  padding-top: 20px;
}

.ticket-panel__body { min-width: 0; }

.ticket-panel h2 {
  color: var(--field-ink);
  font-size: 17px;
  font-weight: 700;
  margin: 0 0 6px;
}

.ticket-panel p {
  color: var(--field-muted);
  font-size: 13px;
  line-height: 1.5;
  margin: 6px 0 0;
}

.ticket-loading {
  align-items: center;
  color: var(--field-ink-soft);
  display: flex;
  gap: 8px;
}

.ticket-status {
  color: var(--field-ink);
  display: inline-flex;
  font-size: 14px;
  font-weight: 700;
  padding: 4px 0;
}

.ticket-status.issued { color: var(--field-teal); }
.ticket-status.failed,
.failure,
.unavailable { color: var(--field-coral); }

/* ============ 刷新按钮 ============ */
.ticket-refresh {
  background: transparent;
  border: 1px solid var(--field-teal);
  border-radius: var(--travel-radius-sm);
  color: var(--field-teal);
  cursor: pointer;
  flex: 0 0 auto;
  font-weight: 800;
  font-size: 13px;
  min-height: 40px;
  padding: 0 14px;
  transition: background-color var(--motion-base) var(--ease-standard), border-color var(--motion-base) var(--ease-standard), color var(--motion-base) var(--ease-standard), transform var(--motion-base) var(--ease-standard);
}

.ticket-refresh:hover:not(:disabled) {
  background: var(--field-deep);
  border-color: var(--field-deep);
  color: var(--field-white);
  transform: translateY(-1px);
}

.ticket-refresh:active:not(:disabled) { transform: translateY(0) scale(0.98); }

.ticket-refresh:disabled { cursor: wait; opacity: 0.55; }

.ticket-refresh:focus-visible { outline: 3px solid var(--field-saffron); outline-offset: 3px; }

/* ============ 响应式 ============ */
@media (max-width: 600px) {
  .ticket-panel { align-items: stretch; flex-direction: column; }
  .ticket-refresh { width: 100%; }
}

@media (prefers-reduced-motion: reduce) {
  .ticket-refresh { transition: none; }
}
</style>
