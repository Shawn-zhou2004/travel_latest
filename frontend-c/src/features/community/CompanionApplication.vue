<script setup lang="ts">
import { Check, Clock3, UserPlus } from 'lucide-vue-next'
import { computed } from 'vue'
const props = defineProps<{ status: 'idle' | 'applying' | 'pending' | 'accepted' | 'rejected'; error?: string }>()
const emit = defineEmits<{ apply: [] }>()
const title = computed(() => ({ idle: '加入这段同行', applying: '正在发送申请', pending: '等待同行邀请', accepted: '你已加入同行群聊', rejected: '这次没有匹配成功' })[props.status])
</script>
<template><section class="application" aria-live="polite"><div class="application-icon"><UserPlus v-if="props.status === 'idle' || props.status === 'applying'" :size="21" /><Clock3 v-else-if="props.status === 'pending'" :size="21" /><Check v-else :size="21" /></div><div><p class="eyebrow">COMPANION REQUEST</p><h2>{{ title }}</h2><p v-if="props.status === 'idle'">向发起人表达你的同行期待。</p><p v-else-if="props.status === 'pending'">发起人确认后，同行群聊会自动开启。</p><p v-else-if="props.status === 'accepted'">可以前往群聊，继续把路线聊清楚。</p><p v-else-if="props.status === 'rejected'">继续留意其他适合你的同行邀请。</p><el-alert v-if="props.error" :title="props.error" type="error" :closable="false"/><el-button v-if="props.status === 'idle'" type="primary" @click="emit('apply')">申请同行</el-button><el-button v-else-if="props.status === 'applying'" type="primary" loading>发送中</el-button></div></section></template>
<style scoped>
.application {
  background: var(--field-white);
  border: 1px solid var(--field-line);
  border-top: 3px solid var(--field-coral);
  border-radius: var(--travel-radius-sm);
  box-shadow: var(--shadow-soft);
  display: flex;
  gap: 15px;
  padding: 24px;
  animation: reveal-soft var(--motion-slow) var(--ease-out) both;
}
.application-icon {
  align-items: center;
  background: var(--field-teal-soft);
  border-radius: 50%;
  color: var(--field-teal);
  display: inline-flex;
  flex: 0 0 auto;
  height: 42px;
  justify-content: center;
  transition: background-color var(--motion-base) var(--ease-standard), color var(--motion-base) var(--ease-standard), transform var(--motion-base) var(--ease-out);
  width: 42px;
}
.application:hover .application-icon { transform: scale(1.06); }
.eyebrow { color: var(--field-teal); font: 800 10px var(--field-mono); letter-spacing: .1em; margin: 0; }
.application h2 { color: var(--field-ink); font-size: 21px; margin: 7px 0; transition: color var(--motion-fast) var(--ease-standard); }
.application p:not(.eyebrow) { color: var(--field-ink-soft); line-height: 1.6; margin: 0; }
.application :deep(.el-alert) { margin: 12px 0; }
.application :deep(.el-button) { margin-top: 16px; }
@media (prefers-reduced-motion: reduce) {
  .application { animation: none; }
  .application-icon, .application h2 { transition: none; }
}
</style>
