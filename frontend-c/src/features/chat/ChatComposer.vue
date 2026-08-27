<script setup lang="ts">
import { ref } from 'vue'
const props = defineProps<{ disabled?: boolean; reconnecting?: boolean }>()
const emit = defineEmits<{ send: [body: string] }>()
const body = ref('')
function send() { if (!body.value.trim() || props.disabled || props.reconnecting) return; emit('send', body.value.trim()); body.value = '' }
</script>

<template>
  <form class="composer" @submit.prevent="send">
    <label class="composer-label" for="chat-message">分享一个行程想法</label>
    <div class="composer-row">
      <el-input id="chat-message" v-model="body" :disabled="disabled || reconnecting" placeholder="写下路线、集合时间或旅行灵感" @keydown.enter.exact.prevent="send"/>
      <el-button class="composer-submit" type="primary" native-type="submit" :disabled="disabled || reconnecting || !body.trim()">发送</el-button>
    </div>
    <Transition name="slide-down">
      <p v-if="reconnecting" class="composer-notice" role="status">正在恢复连接，恢复后即可继续发送消息。</p>
    </Transition>
  </form>
</template>

<style scoped>
.composer {
  background: var(--field-white);
  border-top: 1px solid var(--field-line);
  padding: 16px 24px 18px;
}

.composer-label {
  color: var(--field-ink-soft);
  display: block;
  font-size: 12px;
  font-weight: 800;
  margin-bottom: 8px;
}

.composer-row {
  display: grid;
  gap: 10px;
  grid-template-columns: minmax(0, 1fr) auto;
}

.composer :deep(.el-input__wrapper) {
  background: var(--field-paper);
  border-radius: var(--travel-radius-sm);
  box-shadow: 0 0 0 1px var(--field-line) inset;
  min-height: 42px;
  padding: 1px 13px;
  transition: box-shadow var(--motion-base) var(--ease-standard);
}

.composer :deep(.el-input__wrapper:hover) {
  box-shadow: 0 0 0 1px color-mix(in srgb, var(--field-teal) 50%, var(--field-line)) inset;
}

.composer :deep(.el-input__wrapper.is-focus) {
  box-shadow: 0 0 0 2px var(--field-teal) inset, 0 0 0 4px var(--field-teal-soft) inset;
}

.composer :deep(.el-input__inner) {
  color: var(--field-ink);
  font-size: 14px;
}

.composer :deep(.el-button) {
  background: var(--field-deep);
  border-color: var(--field-deep);
  border-radius: var(--travel-radius-sm);
  color: var(--field-white);
  font-weight: 800;
  min-height: 42px;
  padding: 0 19px;
  transition: background-color var(--motion-base) var(--ease-standard), border-color var(--motion-base) var(--ease-standard), transform var(--motion-base) var(--ease-standard), opacity var(--motion-base) var(--ease-standard);
}

.composer :deep(.el-button:hover:not(.is-disabled)),
.composer :deep(.el-button:focus-visible) {
  background: var(--field-teal);
  border-color: var(--field-teal);
}

.composer :deep(.el-button:active:not(.is-disabled)) { transform: scale(0.98); }

.composer :deep(.el-button.is-disabled) {
  background: var(--field-muted);
  border-color: var(--field-muted);
  cursor: not-allowed;
  opacity: 0.55;
}

.composer-notice {
  color: var(--field-saffron);
  font-size: 12px;
  margin: 9px 0 0;
}

@media (max-width: 720px) { .composer { padding: 14px 16px 16px; } }

@media (max-width: 480px) {
  .composer-row { grid-template-columns: 1fr; }
  .composer :deep(.el-button) { margin: 0; width: 100%; }
}

@media (prefers-color-scheme: dark) {
  .composer { background: #152a26; border-color: #31534c; }
  .composer-label { color: #b5cbc3; }
  .composer :deep(.el-input__wrapper) { background: #10201d; box-shadow: 0 0 0 1px #31534c inset; }
  .composer :deep(.el-input__wrapper:hover) { box-shadow: 0 0 0 1px #4a7a72 inset; }
  .composer :deep(.el-input__inner) { color: #e5f0eb; }
  .composer :deep(.el-button) { background: #3c9885; border-color: #3c9885; color: #08231d; }
  .composer :deep(.el-button:hover:not(.is-disabled)),
  .composer :deep(.el-button:focus-visible) { background: #70c4ae; border-color: #70c4ae; }
  .composer :deep(.el-button.is-disabled) { background: #2a4a43; border-color: #2a4a43; color: #8aa39c; }
}

@media (prefers-reduced-motion: reduce) {
  .composer :deep(.el-input__wrapper),
  .composer :deep(.el-button) { transition: none; }
}
</style>
