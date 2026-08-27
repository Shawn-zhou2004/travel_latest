<script setup lang="ts">
export interface ChatMessage { id: string; client_message_id?: string; sender_id: string; body_text?: string | null; created_at: string; delivery?: 'sending' | 'sent' | 'failed' }
defineProps<{ messages: ChatMessage[]; currentUserId: string; reconnecting?: boolean; error?: string }>()
</script>

<template>
  <section class="history" aria-live="polite" aria-label="消息记录">
    <header class="history-heading">
      <span>LIVE THREAD</span>
      <p>{{ messages.length ? `${messages.length} 条消息` : '旅程从这里开始' }}</p>
    </header>
    <el-alert v-if="reconnecting" title="正在重新连接，恢复后会检查最近消息。" type="warning" :closable="false"/>
    <el-alert v-else-if="error" :title="error" type="error" :closable="false"/>
    <div v-else-if="messages.length === 0" class="empty">
      <span aria-hidden="true">+</span>
      <p>还没有消息</p>
      <small>从路线、时间或想去的地方开始聊。</small>
    </div>
    <ol v-else>
      <li v-for="message in messages" :key="message.id" :class="{ mine: message.sender_id === currentUserId }">
        <p>{{ message.body_text }}</p>
        <small>{{ new Date(message.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) }}<template v-if="message.delivery"> · {{ message.delivery }}</template></small>
      </li>
    </ol>
  </section>
</template>

<style scoped>
.history {
  background: var(--field-paper);
  min-height: 0;
  overflow: auto;
  padding: 20px 24px 28px;
}

.history-heading {
  align-items: center;
  display: flex;
  justify-content: space-between;
  margin: 0 0 24px;
}

.history-heading span {
  color: var(--field-deep);
  font: 800 10px var(--field-mono);
  letter-spacing: 0.12em;
}

.history-heading p {
  color: var(--field-muted);
  font-size: 12px;
  margin: 0;
}

.history :deep(.el-alert) {
  border-radius: var(--travel-radius-sm);
  margin-bottom: 12px;
}

.empty {
  align-content: center;
  color: var(--field-muted);
  display: grid;
  justify-items: center;
  min-height: 330px;
  text-align: center;
}

.empty span {
  align-items: center;
  border: 1px solid var(--field-line);
  border-radius: 50%;
  color: var(--field-teal);
  display: inline-flex;
  font-size: 22px;
  height: 44px;
  justify-content: center;
  width: 44px;
}

.empty p {
  color: var(--field-ink);
  font-size: 16px;
  font-weight: 800;
  margin: 14px 0 5px;
}

.empty small {
  color: var(--field-muted);
  font-size: 13px;
}

.history ol {
  display: grid;
  gap: 12px;
  list-style: none;
  margin: 0;
  padding: 0;
}

.history li {
  background: var(--field-white);
  border: 1px solid var(--field-line);
  border-radius: 4px 12px 12px 12px;
  box-shadow: var(--shadow-soft);
  color: var(--field-ink);
  max-width: min(76%, 570px);
  padding: 11px 14px 9px;
  transition: background-color var(--motion-base) var(--ease-standard), border-color var(--motion-base) var(--ease-standard);
}

.history li.mine {
  background: var(--field-teal-soft);
  border-color: color-mix(in srgb, var(--field-teal) 30%, var(--field-line));
  border-radius: 12px 4px 12px 12px;
  justify-self: end;
}

.history li p {
  line-height: 1.55;
  margin: 0;
  overflow-wrap: anywhere;
}

.history li small {
  color: var(--field-muted);
  display: block;
  font-size: 11px;
  margin-top: 6px;
}

@media (max-width: 720px) {
  .history { padding: 18px 16px 24px; }
  .history li { max-width: 88%; }
}

@media (prefers-color-scheme: dark) {
  .history { background: #10201d; }
  .history-heading span { color: #70c4ae; }
  .history-heading p,
  .empty,
  .history li small { color: #a2b6ae; }
  .empty p,
  .history li { color: #e5f0eb; }
  .empty span { border-color: #477168; color: #70c4ae; }
  .history li { background: #18312c; border-color: #31534c; box-shadow: none; }
  .history li.mine { background: #235d52; border-color: #3e8878; }
}

@media (prefers-reduced-motion: reduce) {
  .history li { transition: none; }
}
</style>
