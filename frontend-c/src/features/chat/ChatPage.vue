<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { getPrivateImageUrl } from '@/features/media/api'
import ChatComposer from './ChatComposer.vue'
import ChatHistory from './ChatHistory.vue'
import { connectConversationRealtime, listConversations, listMessages, mergeChatMessages, sendMessage as sendChatMessage, type ChatMessage, type Conversation } from './api'
import { useReveal } from '@/composables/useReveal'
import { newClientId } from '@/services/id'

const props = defineProps<{ conversationId?: string }>()
const router = useRouter()
const auth = useAuthStore()
const messages = ref<ChatMessage[]>([])
const error = ref('')
const reconnecting = ref(false)
const conversations = ref<Conversation[]>([])
const nextCursor = ref<string | null>(null)
const conversationAvatarUrls = ref<Record<string, string>>({})
let disconnectRealtime: (() => void) | undefined
const root = ref<HTMLElement | null>(null)
useReveal(root)

function mergeMessages(incoming: ChatMessage[]) {
  messages.value = mergeChatMessages(messages.value, incoming)
}

async function loadMessages() {
  if (!props.conversationId) {
    error.value = 'Choose a conversation to start messaging.'
    return
  }
  error.value = ''
  try {
    const response = await listMessages(props.conversationId)
    mergeMessages(response.items)
    window.dispatchEvent(new Event('unread-counts:refresh'))
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : 'Messages could not be loaded.'
  }
}

function closeSocket() {
  disconnectRealtime?.()
  disconnectRealtime = undefined
  reconnecting.value = false
}

function connectSocket() {
  const conversationId = props.conversationId
  if (!conversationId) return
  disconnectRealtime = connectConversationRealtime(conversationId, (payload) => {
    mergeMessages([payload.message])
    window.dispatchEvent(new Event('unread-counts:refresh'))
  }, (isReconnecting, recovered) => {
    reconnecting.value = isReconnecting
    if (recovered) void loadMessages()
  })
}

async function sendMessage(body: string) {
  if (!props.conversationId) return
  try {
    const clientMessageId = newClientId()
    const pending: ChatMessage = { id: clientMessageId, conversation_id: props.conversationId, client_message_id: clientMessageId, sender_id: auth.user?.id ?? '', message_type: 'text', body_text: body, payload_json: null, created_at: new Date().toISOString(), delivery: 'sending' }
    messages.value.push(pending)
    const response = await sendChatMessage(props.conversationId, clientMessageId, body)
    mergeMessages([response])
    error.value = ''
    window.dispatchEvent(new Event('unread-counts:refresh'))
  } catch (reason) {
    messages.value = messages.value.map((message) => message.delivery === 'sending' ? { ...message, delivery: 'failed' } : message)
    error.value = reason instanceof Error ? reason.message : 'Message could not be sent.'
  }
}

async function loadConversations() {
  try {
    const response = await listConversations()
    conversations.value = response.items
    nextCursor.value = response.next_cursor
    await Promise.all(response.items.filter((conversation) => conversation.avatar_asset_id).map(async (conversation) => {
      try { conversationAvatarUrls.value[conversation.id] = await getPrivateImageUrl(conversation.avatar_asset_id!) } catch { /* Keep the initial avatar when media is unavailable. */ }
    }))
    if (!props.conversationId && response.items[0]) {
      await router.replace(`/messages/${response.items[0].id}`)
    }
  } catch {
    error.value = '会话列表暂时无法读取。'
  }
}

onMounted(async () => { await Promise.all([loadConversations(), loadMessages()]); connectSocket() })
watch(() => props.conversationId, async () => { closeSocket(); messages.value = []; await loadMessages(); connectSocket() })
onUnmounted(closeSocket)
</script>

<template>
  <main class="chat-page" ref="root">
    <header class="page-heading" data-reveal>
      <p>TRIP COORDINATION</p>
      <div>
        <h1>同行消息</h1>
        <span>把路线、约定与灵感留在同一段旅程里。</span>
      </div>
    </header>
    <div class="chat-layout">
      <aside class="conversation-list" aria-label="会话列表">
        <div class="conversation-list-heading">
          <div>
            <p>YOUR CIRCLES</p>
            <h2>会话</h2>
          </div>
          <span class="conversation-count">{{ conversations.length }}</span>
        </div>
        <Transition name="fade">
          <p v-if="!conversations.length" class="conversation-empty">暂无可用群聊</p>
        </Transition>
        <RouterLink
          v-for="conversation in conversations"
          :key="conversation.id"
          class="conversation-item reveal"
          :to="`/messages/${conversation.id}`"
          :class="{ selected: conversation.id === props.conversationId }"
        >
          <span class="conversation-mark">
            <img v-if="conversationAvatarUrls[conversation.id]" :src="conversationAvatarUrls[conversation.id]" :alt="`${conversation.title || '结伴群聊'}头像`" />
            <span v-else aria-hidden="true">{{ (conversation.title || (conversation.conversation_type === 'direct' ? '私聊' : '结伴群聊')).slice(0, 1) }}</span>
          </span>
          <span class="conversation-copy">
            <strong>{{ conversation.title || (conversation.conversation_type === 'direct' ? '私聊' : '结伴群聊') }}</strong>
            <span>{{ conversation.unread_count ? `${conversation.unread_count} 条未读` : conversation.last_message?.body_text || '暂无消息' }}</span>
          </span>
          <i v-if="conversation.unread_count" aria-label="有未读消息"></i>
        </RouterLink>
      </aside>
      <section class="conversation-panel" aria-label="当前会话">
        <Transition name="fade">
          <p v-if="!props.conversationId && conversations.length" class="conversation-empty conversation-empty--inline">正在打开最近聊天的群聊...</p>
        </Transition>
        <ChatHistory :messages="messages" :current-user-id="auth.user?.id ?? ''" :reconnecting="reconnecting" :error="error" />
        <ChatComposer :disabled="!props.conversationId" :reconnecting="reconnecting" @send="sendMessage" />
      </section>
    </div>
  </main>
</template>

<style scoped>
/* ============ 页面容器 ============ */
.chat-page {
  --ink: var(--field-ink);
  --muted: var(--field-muted);
  --line: var(--field-line);
  --mist: var(--field-paper);
  --pine: var(--field-deep);
  --amber: var(--field-saffron);
  color: var(--ink);
  margin: 0 auto;
  max-width: 1120px;
  padding: 38px 24px 64px;
}

.chat-page ::-webkit-scrollbar { width: 6px; height: 6px; }
.chat-page ::-webkit-scrollbar-track { background: transparent; }
.chat-page ::-webkit-scrollbar-thumb { background: var(--field-line); border-radius: 3px; transition: background var(--motion-fast) var(--ease-standard); }
.chat-page ::-webkit-scrollbar-thumb:hover { background: var(--field-teal); }

/* ============ 页头 ============ */
.page-heading {
  align-items: flex-end;
  display: flex;
  gap: 20px;
  justify-content: space-between;
  margin: 0 0 24px;
}

.page-heading > p,
.conversation-list-heading p {
  color: var(--pine);
  font: 800 10px/1.2 var(--field-mono);
  letter-spacing: 0.12em;
  margin: 0 0 8px;
}

.page-heading h1 {
  color: var(--ink);
  font-size: clamp(30px, 4vw, 42px);
  letter-spacing: 0;
  line-height: 1.1;
  margin: 0;
}

.page-heading span {
  color: var(--muted);
  display: block;
  font-size: 14px;
  margin-top: 8px;
}

/* ============ 聊天布局 ============ */
.chat-layout {
  background: var(--field-white);
  border: 1px solid var(--line);
  border-radius: 14px;
  box-shadow: var(--shadow-lift);
  display: grid;
  grid-template-columns: 300px minmax(0, 1fr);
  min-height: 620px;
  overflow: hidden;
}

/* ============ 会话列表 ============ */
.conversation-list {
  align-content: start;
  background: var(--mist);
  border-right: 1px solid var(--line);
  display: grid;
  padding: 18px 12px;
}

.conversation-list-heading {
  align-items: center;
  display: flex;
  justify-content: space-between;
  padding: 4px 10px 16px;
}

.conversation-list-heading p { margin-bottom: 6px; }

.conversation-list-heading h2 {
  color: var(--ink);
  font-size: 18px;
  margin: 0;
}

.conversation-count {
  align-items: center;
  background: color-mix(in srgb, var(--pine) 14%, transparent);
  border-radius: 999px;
  color: var(--pine);
  display: inline-flex;
  font: 800 12px var(--field-mono);
  height: 26px;
  justify-content: center;
  min-width: 26px;
}

.conversation-empty {
  color: var(--muted);
  font-size: 13px;
  margin: 10px;
  padding: 18px 0;
  text-align: center;
}

.conversation-empty--inline { padding: 12px 16px; }

.conversation-item {
  align-items: center;
  border-radius: 9px;
  color: var(--ink);
  display: grid;
  gap: 10px;
  grid-template-columns: 34px minmax(0, 1fr) auto;
  margin: 1px 0;
  padding: 11px 10px;
  text-decoration: none;
  transition: background-color var(--motion-base) var(--ease-standard), transform var(--motion-base) var(--ease-standard), box-shadow var(--motion-base) var(--ease-standard);
}

.conversation-item:hover { background: color-mix(in srgb, var(--pine) 9%, transparent); }

.conversation-item:active { transform: scale(0.99); }

.conversation-item.selected {
  background: var(--pine);
  box-shadow: 0 7px 16px color-mix(in srgb, var(--pine) 22%, transparent);
  color: var(--field-white);
}

.conversation-item:focus-visible { outline: 3px solid var(--field-saffron); outline-offset: 2px; }

.conversation-mark {
  align-items: center;
  background: color-mix(in srgb, var(--pine) 14%, transparent);
  border-radius: 50%;
  color: var(--pine);
  display: inline-flex;
  font-size: 14px;
  font-weight: 800;
  height: 34px;
  justify-content: center;
  width: 34px;
}

.conversation-mark img { border-radius: inherit; height: 100%; object-fit: cover; width: 100%; }

.conversation-item.selected .conversation-mark {
  background: rgba(255, 255, 255, 0.16);
  color: var(--field-white);
}

.conversation-copy {
  display: grid;
  gap: 4px;
  min-width: 0;
}

.conversation-copy strong {
  font-size: 14px;
  line-height: 1.25;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.conversation-copy > span {
  color: var(--muted);
  font-size: 12px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.conversation-item.selected .conversation-copy > span { color: rgba(255, 255, 255, 0.72); }

.conversation-list i {
  background: var(--amber);
  border: 2px solid var(--mist);
  border-radius: 50%;
  display: block;
  height: 9px;
  width: 9px;
}

.conversation-item.selected i { border-color: var(--pine); }

.conversation-item:nth-child(1) { --reveal-index: 0; }
.conversation-item:nth-child(2) { --reveal-index: 1; }
.conversation-item:nth-child(3) { --reveal-index: 2; }
.conversation-item:nth-child(n+4) { --reveal-index: 3; }

/* ============ 当前会话面板 ============ */
.conversation-panel {
  display: grid;
  grid-template-rows: minmax(0, 1fr) auto;
  min-width: 0;
}

/* ============ 响应式 ============ */
@media (max-width: 720px) {
  .chat-page { padding: 24px 16px 40px; }
  .page-heading { align-items: flex-start; display: grid; gap: 4px; }
  .chat-layout { grid-template-columns: 1fr; min-height: 0; }
  .conversation-list { border-bottom: 1px solid var(--line); border-right: 0; max-height: 280px; overflow: auto; }
  .conversation-panel { min-height: 470px; }
}

@media (prefers-color-scheme: dark) {
  .chat-page { --ink: #e5f0eb; --muted: #a2b6ae; --line: #31534c; --mist: #152a26; --pine: #70c4ae; }
  .chat-layout { background: #10201d; box-shadow: 0 18px 44px rgba(0, 0, 0, 0.2); }
  .conversation-count,
  .conversation-mark { background: #254840; color: #a2e1d0; }
  .conversation-item:hover { background: #1c3933; }
  .conversation-item.selected { background: #267062; }
  .conversation-list i { border-color: #152a26; }
  .conversation-item.selected i { border-color: #267062; }
}

@media (prefers-reduced-motion: reduce) {
  .conversation-item { transition: none; }
}
</style>
