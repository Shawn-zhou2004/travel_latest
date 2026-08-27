<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RefreshCw } from 'lucide-vue-next'
import { RouterLink } from 'vue-router'
import { getPrivateImageUrl } from '@/features/media/api'
import { getUnreadSummary, type GroupUnreadSummary } from './api'
import { useReveal } from '@/composables/useReveal'

const root = ref<HTMLElement | null>(null)
useReveal(root)

const groups = ref<GroupUnreadSummary[]>([])
const loading = ref(true)
const error = ref('')
const avatarUrls = ref<Record<string, string>>({})
const totalUnread = computed(() => groups.value.reduce((total, group) => total + group.unread_count, 0))

function preview(group: GroupUnreadSummary) { return group.last_message?.body_text || '有新消息' }
function formatTimestamp(value: string | undefined) {
  if (!value) return '暂无消息'
  const timestamp = new Date(value)
  return Number.isNaN(timestamp.getTime()) ? '时间不可用' : new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(timestamp)
}
async function loadGroups() {
  loading.value = true
  error.value = ''
  try {
    groups.value = (await getUnreadSummary()).groups
    const resolved = await Promise.all(groups.value.map(async (group) => {
      if (!group.avatar_asset_id) return null
      try { return [group.conversation_id, await getPrivateImageUrl(group.avatar_asset_id)] as const } catch { return null }
    }))
    avatarUrls.value = Object.fromEntries(resolved.filter((item): item is readonly [string, string] => item !== null))
  } catch (reason) { error.value = reason instanceof Error ? reason.message : '消息暂时无法读取，请稍后重试。' } finally { loading.value = false }
}
onMounted(() => { void loadGroups() })
</script>

<template>
  <main class="notifications" aria-labelledby="notifications-title" ref="root">
    <header class="notification-header" data-reveal><div><h1 id="notifications-title">群聊消息</h1><p class="unread-status" aria-live="polite">{{ totalUnread ? `${totalUnread} 条未读消息` : '全部已读' }}</p></div><button type="button" class="icon-button" title="刷新群聊消息" :disabled="loading" @click="loadGroups"><RefreshCw :size="18" :class="{ spinning: loading }" /><span class="sr-only">刷新群聊消息</span></button></header>
    <p v-if="loading" class="state" role="status">正在读取群聊消息...</p>
    <section v-else-if="error" class="state unavailable" role="alert"><strong>群聊消息暂时不可用</strong><p>{{ error }}</p><button type="button" @click="loadGroups">重试</button></section>
    <section v-else-if="groups.length" class="notification-list" aria-label="群聊未读消息"><RouterLink v-for="group in groups" :key="group.conversation_id" class="group-item" :to="`/messages/${group.conversation_id}`"><div class="avatar" aria-hidden="true"><img v-if="avatarUrls[group.conversation_id]" :src="avatarUrls[group.conversation_id]" alt="" /> <template v-else>{{ group.title.slice(0, 1) }}</template></div><div class="group-copy"><h2>{{ group.title }}</h2><p>{{ preview(group) }}</p><time :datetime="group.last_message?.created_at">{{ formatTimestamp(group.last_message?.created_at) }}</time></div><span class="unread-count" :aria-label="`${group.unread_count} 条未读消息`">{{ group.unread_count > 99 ? '99+' : group.unread_count }}</span></RouterLink></section>
    <section v-else class="state empty"><strong>没有未读群聊消息</strong><p>新的群聊消息会显示在这里。</p></section>
  </main>
</template>

<style scoped>
.notifications { color: var(--field-ink); margin: 0 auto; max-width: 800px; padding: 48px 24px 80px; }.notification-header { animation: header-enter var(--motion-slow) var(--ease-out) both; align-items: center; border-bottom: 2px solid var(--field-ink); display: flex; justify-content: space-between; padding-bottom: 18px; }.notification-header h1 { font-size: 38px; margin: 0; }.unread-status { background: var(--field-teal-soft); border-radius: 999px; color: var(--field-teal); display: inline-block; font: 700 12px/1.4 var(--field-mono); margin: 8px 0 0; padding: 5px 9px; }.icon-button, .unavailable button { align-items: center; background: transparent; border: 1px solid var(--field-teal); color: var(--field-teal); cursor: pointer; display: inline-flex; gap: 7px; justify-content: center; min-height: 40px; padding: 0 12px; }.group-item { align-items: center; background: var(--field-white); border: 1px solid var(--field-line); border-radius: 9px; color: inherit; display: flex; gap: 15px; margin-top: 10px; padding: 16px; text-decoration: none; transition: border-color var(--motion-fast) var(--ease-standard), box-shadow var(--motion-fast) var(--ease-standard), transform var(--motion-fast) var(--ease-standard); }.group-item:hover { border-color: var(--field-teal); box-shadow: var(--shadow-soft); transform: translateY(-1px); }.group-item:focus-visible { border-color: var(--field-teal); box-shadow: var(--shadow-soft); transform: translateY(-1px); }.avatar { align-items: center; background: var(--field-teal-soft); border-radius: 50%; color: var(--field-teal); display: flex; flex: 0 0 auto; font-size: 20px; font-weight: 800; height: 48px; justify-content: center; overflow: hidden; width: 48px; }.avatar img { height: 100%; object-fit: cover; width: 100%; }.group-copy { min-width: 0; }.group-copy h2 { font-size: 17px; margin: 0; }.group-copy p { margin: 5px 0 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }.group-copy time { color: var(--field-muted); display: block; font: 12px/1.5 var(--field-mono); margin-top: 5px; }.unread-count { background: var(--field-saffron); border-radius: 999px; color: var(--field-deep); font: 800 12px var(--field-mono); margin-left: auto; min-width: 25px; padding: 5px 7px; text-align: center; }.state { animation: content-enter var(--motion-slow) var(--ease-out) both; background: var(--field-white); border: 1px solid var(--field-line); margin-top: 28px; padding: 20px; }.state p { color: var(--field-ink-soft); margin: 7px 0 15px; }.spinning { animation: spin .75s linear infinite; }.sr-only { height: 1px; margin: -1px; overflow: hidden; position: absolute; width: 1px; clip: rect(0, 0, 0, 0); } @keyframes spin { to { transform: rotate(360deg); } }

.notification-list { animation: content-enter var(--motion-slow) var(--ease-out) both; }

/* ============ 交互态 ============ */
.icon-button:not(:disabled):hover, .unavailable button:hover { background: var(--field-teal-soft); transform: translateY(-1px); }
.icon-button:not(:disabled):active, .unavailable button:active { transform: translateY(0) scale(0.96); }
.icon-button:focus-visible, .unavailable button:focus-visible { outline: 3px solid var(--field-saffron); outline-offset: 2px; }
.icon-button:disabled { cursor: not-allowed; opacity: .6; }
.group-item:active { transform: translateY(0) scale(0.99); }

@keyframes header-enter { from { opacity: 0; transform: translateY(-10px); } to { opacity: 1; transform: translateY(0); } }
@keyframes content-enter { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: translateY(0); } }

@media (prefers-reduced-motion: reduce) {
  .notification-header, .state, .notification-list { animation: none; }
  .spinning { animation: none; }
  .group-item, .icon-button, .unavailable button { transition: none; }
  .group-item:hover, .group-item:focus-visible, .icon-button:not(:disabled):hover, .unavailable button:hover { transform: none; }
} @media (max-width: 580px) { .notifications { padding: 30px 16px 56px; }.notification-header h1 { font-size: 30px; }.group-copy p { max-width: 52vw; } }
</style>
