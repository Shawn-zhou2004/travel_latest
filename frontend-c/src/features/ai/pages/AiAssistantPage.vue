<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { Bot, CircleAlert, FileText, MapPinned, MessageSquarePlus, Pencil, Plus, Send, Trash2 } from 'lucide-vue-next'
import { ElMessage } from 'element-plus/es/components/message/index'
import { normalizeApiError } from '@/services/api'
import { createAiConversation, createAiMemory, deleteAiConversation, deleteAiMemory, listAiConversations, listAiMemories, listAiMessages, replayAiAssistantRun, streamAiAssistant, updateAiMemory, type AiConversation, type AiMemory, type AiMessage } from '../assistantApi'
import { listItineraries, type ItineraryRecord } from '@/features/itineraries/api'
import { useAiPlanningStore } from '@/features/itineraries/stores/aiPlanning'
import { getMySettings, type UserSettings } from '@/features/settings/api'
import { useReveal } from '@/composables/useReveal'

const conversations = ref<AiConversation[]>([])
const memories = ref<AiMemory[]>([])
const messages = ref<AiMessage[]>([])
const activeId = ref('')
const prompt = ref('')
const loading = ref(true)
const asking = ref(false)
const itineraries = ref<ItineraryRecord[]>([])
const selectedItineraryId = ref('')
const modificationPrompt = ref('')
const modifying = ref(false)
const error = ref('')
const streamStatus = ref('')
const savedSettings = ref<UserSettings | null>(null)
const memoryDialogOpen = ref(false)
const editingMemory = ref<AiMemory | null>(null)
const memoryType = ref<AiMemory['memory_type']>('profile')
const memoryKey = ref('')
const memoryTextValue = ref('')
const savingMemory = ref(false)
const memoryError = ref('')
const activeConversation = computed(() => conversations.value.find((item) => item.id === activeId.value))
const selectedItinerary = computed(() => itineraries.value.find((item) => item.id === selectedItineraryId.value))
const planning = useAiPlanningStore()
const root = ref<HTMLElement | null>(null)
useReveal(root)
const streamEl = ref<HTMLElement | null>(null)

function scrollToBottom() {
  const el = streamEl.value
  if (el) el.scrollTop = el.scrollHeight
}

// 流式回答时跟随滚动；用户主动上翻阅读历史时不打扰
async function followStream() {
  const el = streamEl.value
  if (!el || el.scrollHeight - el.scrollTop - el.clientHeight >= 140) return
  await nextTick()
  scrollToBottom()
}

watch(messages, followStream, { deep: true })

function messageText(message: AiMessage) { return typeof message.content.text === 'string' ? message.content.text : '此消息无法显示。' }
function citations(message: AiMessage) { return Array.isArray(message.content.citations) ? message.content.citations : [] }
function memoryText(memory: AiMemory) { return typeof memory.memory_value.text === 'string' ? memory.memory_value.text : JSON.stringify(memory.memory_value) }
async function loadConversation(id: string) { activeId.value = id; messages.value = []; try { messages.value = await listAiMessages(id); await nextTick(); scrollToBottom() } catch (cause) { error.value = normalizeApiError(cause).message } }
async function createConversation() { try { const conversation = await createAiConversation('旅行助手'); conversations.value.unshift(conversation); await loadConversation(conversation.id) } catch (cause) { error.value = normalizeApiError(cause).message } }
async function removeConversation(conversation: AiConversation) {
  if (asking.value || !window.confirm('删除这段对话及其回答？此操作无法撤销。')) return
  try {
    await deleteAiConversation(conversation.id)
    conversations.value = conversations.value.filter((item) => item.id !== conversation.id)
    if (activeId.value === conversation.id) {
      messages.value = []
      activeId.value = ''
      if (conversations.value[0]) await loadConversation(conversations.value[0].id)
      else await createConversation()
    }
  } catch (cause) { error.value = normalizeApiError(cause).message }
}
async function ask() {
  const text = prompt.value.trim()
  if (!activeId.value || !text || asking.value) return
  asking.value = true
  error.value = ''
  streamStatus.value = '正在检索已审核旅行资料'
  const optimistic: AiMessage = { id: crypto.randomUUID(), role: 'user', content: { text }, client_message_id: null, created_at: new Date().toISOString() }
  const provisional: AiMessage = { id: crypto.randomUUID(), role: 'assistant', content: { text: '' }, client_message_id: null, created_at: new Date().toISOString() }
  let runId = ''
  messages.value.push(optimistic, provisional)
  prompt.value = ''
  await nextTick()
  scrollToBottom()
  const onEvent = (event: Parameters<typeof streamAiAssistant>[2] extends (value: infer Event) => void ? Event : never) => {
    runId = event.runId
    if (event.type === 'progress') streamStatus.value = event.message
    if (event.type === 'delta') provisional.content.text = `${provisional.content.text ?? ''}${event.text}`
    if (event.type === 'completed') { messages.value = messages.value.filter((item) => item.id !== provisional.id); messages.value.push(event.message); streamStatus.value = '' }
    if (event.type === 'failed') { messages.value = messages.value.filter((item) => item.id !== provisional.id); error.value = event.message; streamStatus.value = '' }
  }
  try {
    await streamAiAssistant(activeId.value, { text, client_message_id: crypto.randomUUID() }, onEvent)
  } catch (cause) {
    if (runId) {
      try { await replayAiAssistantRun(runId, onEvent) } catch { error.value = normalizeApiError(cause).message }
    } else error.value = normalizeApiError(cause).message
  } finally {
    if (runId) await loadConversation(activeId.value)
    messages.value = messages.value.filter((item) => item.id !== optimistic.id && item.id !== provisional.id)
    asking.value = false
    streamStatus.value = ''
  }
}
async function removeMemory(memory: AiMemory) { try { await deleteAiMemory(memory.id); memories.value = memories.value.filter((item) => item.id !== memory.id); ElMessage.success('这条记忆已删除。') } catch (cause) { ElMessage.error(normalizeApiError(cause).message) } }
function openCreateMemory() {
  editingMemory.value = null
  memoryType.value = 'profile'
  memoryKey.value = ''
  memoryTextValue.value = ''
  memoryError.value = ''
  memoryDialogOpen.value = true
}
function openEditMemory(memory: AiMemory) {
  editingMemory.value = memory
  memoryType.value = memory.memory_type
  memoryKey.value = memory.memory_key
  memoryTextValue.value = memoryText(memory)
  memoryError.value = ''
  memoryDialogOpen.value = true
}
async function saveMemory() {
  const key = memoryKey.value.trim()
  const text = memoryTextValue.value.trim()
  if (!key || !text || savingMemory.value) return
  savingMemory.value = true
  memoryError.value = ''
  try {
    if (editingMemory.value) {
      const updated = await updateAiMemory(editingMemory.value.id, { text }, 'user', editingMemory.value.confidence)
      memories.value = memories.value.map((item) => item.id === updated.id ? updated : item)
      ElMessage.success('记忆已更新。')
    } else {
      const created = await createAiMemory(memoryType.value, key, text)
      memories.value.unshift(created)
      ElMessage.success('记忆已保存。')
    }
    memoryDialogOpen.value = false
  } catch (cause) {
    memoryError.value = normalizeApiError(cause).message
    ElMessage.error(memoryError.value)
  } finally { savingMemory.value = false }
}
async function modifyItinerary() {
  const itinerary = selectedItinerary.value
  const text = modificationPrompt.value.trim()
  if (!itinerary || !text || modifying.value) return
  modifying.value = true
  error.value = ''
  planning.reset()
  await planning.submit({ prompt: text, start_date: itinerary.start_date, end_date: itinerary.end_date, target_itinerary_id: itinerary.id, base_version: itinerary.version })
  if (planning.state === 'ready') modificationPrompt.value = ''
  modifying.value = false
}
onMounted(async () => { try { const [loadedConversations, loadedMemories, loadedItineraries, loadedSettings] = await Promise.all([listAiConversations(), listAiMemories(), listItineraries(), getMySettings().catch(() => null)]); conversations.value = loadedConversations; memories.value = loadedMemories; itineraries.value = loadedItineraries; savedSettings.value = loadedSettings; if (loadedConversations[0]) await loadConversation(loadedConversations[0].id); else await createConversation() } catch (cause) { error.value = normalizeApiError(cause).message } finally { loading.value = false } })
</script>

<template>
  <main class="assistant-page" ref="root">
    <header class="assistant-header">
      <div class="header-copy">
        <p class="eyebrow">SOURCE-GROUNDED TRAVEL ASSISTANT</p>
        <h1>带着来源，问一段路。</h1>
        <p>基于已审核的官方旅行资料回答。直接说目的地和问题，例如“三亚第一天适合去哪些海滨景点？”。</p>
      </div>
    </header>

    <Transition name="fade">
      <p v-if="error" class="error-state" role="alert"><CircleAlert :size="18" />{{ error }}</p>
    </Transition>

    <section class="assistant-desk" :class="{ loading }">
      <aside class="conversation-rail" aria-label="对话列表" data-reveal>
        <div class="rail-heading">
          <div>
            <span class="section-label">CONVERSATIONS</span>
            <h2>对话记录</h2>
          </div>
          <button type="button" title="新建对话" aria-label="新建对话" @click="createConversation"><MessageSquarePlus :size="18" /></button>
        </div>
        <div class="conversation-list">
          <TransitionGroup name="list">
            <div v-for="conversation in conversations" :key="conversation.id" class="conversation-row" :class="{ active: activeId === conversation.id }">
              <button class="conversation-item" type="button" :aria-current="activeId === conversation.id ? 'true' : undefined" @click="loadConversation(conversation.id)">
                <strong>{{ conversation.title || '未命名对话' }}</strong>
                <span>{{ new Date(conversation.updated_at).toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' }) }}</span>
              </button>
              <button class="delete-conversation" type="button" :disabled="asking" title="删除对话" aria-label="删除对话" @click="removeConversation(conversation)"><Trash2 :size="14" /></button>
            </div>
          </TransitionGroup>
          <Transition name="fade">
            <p v-if="!conversations.length && !loading" class="rail-empty">还没有对话。新建一个问题，从这里开始。</p>
          </Transition>
        </div>
      </aside>

      <section class="conversation-panel" aria-label="旅行对话" data-reveal>
        <header class="conversation-title">
          <div>
            <span class="assistant-mark"><Bot :size="18" /></span>
            <div>
              <span class="section-label">TRAVEL RESEARCH</span>
              <h2>{{ activeConversation?.title || '旅行助手' }}</h2>
            </div>
          </div>
          <span class="source-status">{{ streamStatus || '官方旅行知识库' }}</span>
        </header>
        <div class="message-stream" ref="streamEl" aria-live="polite">
          <Transition name="fade">
            <div v-if="!messages.length && !loading" class="empty-message">
              <span class="empty-mark"><MapPinned :size="22" /></span>
              <strong>从一个具体的问题开始。</strong>
              <p>例如：三亚第一天适合去哪些海滨景点？</p>
            </div>
          </Transition>
          <TransitionGroup name="list">
            <article v-for="message in messages" :key="message.id" class="message" :class="message.role">
              <span class="role">{{ message.role === 'user' ? '你' : '旅行助手' }}</span>
              <p>{{ messageText(message) }}</p>
              <details v-if="citations(message).length">
                <summary><FileText :size="15" />查看 {{ citations(message).length }} 条来源</summary>
                <ol>
                  <li v-for="citation in citations(message)" :key="citation.chunk_id">
                    <strong>{{ citation.source_type }}{{ citation.source_host ? ` · ${citation.source_host}` : '' }}</strong>
                    <span>{{ citation.content }}</span>
                  </li>
                </ol>
              </details>
            </article>
          </TransitionGroup>
        </div>
        <form class="ask-form" @submit.prevent="ask">
          <textarea v-model="prompt" :disabled="asking || !activeId" rows="3" maxlength="2000" placeholder="输入旅行问题，例如：三亚第一天适合去哪些海滨景点？"></textarea>
          <div class="compose-footer">
            <span>优先官方知识库，无结果时搜索并读取网页来源</span>
            <button type="submit" :disabled="asking || !prompt.trim() || !activeId" :class="{ 'is-loading': asking }">
              <span>{{ asking ? (streamStatus || '正在生成回答') : '发送问题' }}</span>
              <Send :size="17" :class="{ spin: asking }" />
            </button>
          </div>
        </form>
      </section>

      <aside class="context-rail" data-reveal>
        <section class="plan-tool" aria-labelledby="modify-title">
          <div class="tool-heading">
            <span class="section-label">PLAN REVISION</span>
            <h2 id="modify-title">修改已有行程</h2>
            <p>选择一个当前版本。AI 先生成预览，确认后才写入新版本。</p>
            <small v-if="savedSettings">默认使用个人设置。</small>
          </div>
          <label>目标行程
            <select v-model="selectedItineraryId" :disabled="modifying">
              <option value="">选择一个已有行程</option>
              <option v-for="itinerary in itineraries" :key="itinerary.id" :value="itinerary.id">{{ itinerary.title }} · v{{ itinerary.version }}</option>
            </select>
          </label>
          <textarea v-model="modificationPrompt" :disabled="modifying || !selectedItineraryId" rows="4" maxlength="2000" placeholder="例如：把第二天下午改成室内、适合慢行的安排"></textarea>
          <button class="plan-submit" type="button" :disabled="modifying || !selectedItineraryId || !modificationPrompt.trim()" @click="modifyItinerary">{{ modifying ? '正在生成修改预览' : '生成修改预览' }}</button>
          <Transition name="slide-down">
            <div v-if="planning.message" class="planning-status" role="status">{{ planning.message }}</div>
          </Transition>
          <Transition name="fade">
            <div v-if="planning.preview" class="modify-preview">
              <div>
                <strong>{{ planning.preview.draft.title }}</strong>
                <span>{{ planning.preview.draft.days.length }} 天 · {{ planning.preview.citations.length }} 条来源</span>
              </div>
              <button type="button" :disabled="planning.applyingPreview" @click="planning.applyPreview">{{ planning.applyingPreview ? '写入中' : '确认写入行程' }}</button>
              <RouterLink v-if="planning.appliedItineraryId" :to="`/itineraries/${planning.appliedItineraryId}`">打开已更新行程</RouterLink>
            </div>
          </Transition>
        </section>

        <section class="memory-panel" aria-labelledby="memory-title">
          <div class="memory-heading">
            <div>
              <span class="section-label">SAVED PREFERENCES</span>
              <h2 id="memory-title">我的记忆</h2>
            </div>
            <div>
              <p>只显示你主动保存的偏好。</p>
              <button class="create-memory" type="button" title="新增记忆" aria-label="新增记忆" @click="openCreateMemory"><Plus :size="16" /></button>
            </div>
          </div>
          <Transition name="fade">
            <div v-if="!memories.length" class="empty-memory">尚无保存的旅行偏好。</div>
          </Transition>
          <TransitionGroup name="list">
            <article v-for="memory in memories" :key="memory.id" class="memory-item">
              <div class="memory-head">
                <strong>{{ memory.memory_key }}</strong>
                <span>{{ memory.memory_type === 'profile' ? '偏好' : '旅行片段' }}</span>
              </div>
              <p>{{ memoryText(memory) }}</p>
              <div class="memory-actions">
                <button type="button" title="编辑记忆" aria-label="编辑记忆" @click="openEditMemory(memory)"><Pencil :size="15" /></button>
                <button type="button" title="删除记忆" aria-label="删除记忆" @click="removeMemory(memory)"><Trash2 :size="15" /></button>
              </div>
            </article>
          </TransitionGroup>
        </section>
      </aside>
    </section>
    <el-dialog v-model="memoryDialogOpen" :title="editingMemory ? '编辑记忆' : '新增记忆'" width="min(92vw, 480px)" destroy-on-close>
      <form :aria-label="editingMemory ? '编辑记忆表单' : '新增记忆表单'" @submit.prevent="saveMemory">
        <label class="memory-form-field" for="memory-type">记忆类型
          <select id="memory-type" v-model="memoryType" :disabled="Boolean(editingMemory) || savingMemory">
            <option value="profile">个人偏好</option>
            <option value="episodic">旅行片段</option>
          </select>
        </label>
        <label class="memory-form-field" for="memory-key">记忆名称
          <input id="memory-key" v-model="memoryKey" name="memory-key" maxlength="200" required :disabled="Boolean(editingMemory) || savingMemory">
        </label>
        <label class="memory-form-field" for="memory-text">记忆内容
          <textarea id="memory-text" v-model="memoryTextValue" name="memory-text" rows="5" required :disabled="savingMemory"></textarea>
        </label>
        <p v-if="memoryError" class="memory-form-error" role="alert">{{ memoryError }}</p>
        <div class="memory-dialog-actions">
          <button type="button" :disabled="savingMemory" @click="memoryDialogOpen = false">取消</button>
          <button type="submit" :disabled="savingMemory || !memoryKey.trim() || !memoryTextValue.trim()">{{ savingMemory ? '保存中' : '保存记忆' }}</button>
        </div>
      </form>
    </el-dialog>
  </main>
</template>

<style scoped>
/* ============ 页面容器 ============ */
.assistant-page {
  background: var(--field-paper);
  color: var(--field-ink);
  display: flex;
  flex-direction: column;
  height: calc(100vh - 72px);
  overflow: hidden;
  padding: 24px clamp(18px, 4vw, 64px) 24px;
}

.assistant-header {
  border-bottom: 2px solid transparent;
  border-image: linear-gradient(90deg, var(--field-teal), var(--field-coral) 60%, transparent) 1;
  flex: 0 0 auto;
  margin: 0 auto;
  max-width: 1420px;
  padding: 0 2px 20px;
  width: 100%;
  animation: header-enter var(--motion-slow) var(--ease-out) both;
}

@keyframes header-enter {
  from { opacity: 0; transform: translateY(-10px); }
  to { opacity: 1; transform: translateY(0); }
}

.header-copy { max-width: 730px; }

.eyebrow,
.section-label {
  color: var(--field-coral);
  font: 800 11px var(--field-mono);
  letter-spacing: 0.12em;
  margin: 0 0 10px;
  text-transform: uppercase;
}

.assistant-header h1 {
  font-family: Georgia, "Noto Serif SC", serif;
  font-size: clamp(32px, 4vw, 52px);
  font-weight: 600;
  letter-spacing: -0.01em;
  line-height: 1.08;
  margin: 0;
}

.assistant-header p {
  color: var(--field-ink-soft);
  font-size: 14px;
  line-height: 1.65;
  margin: 14px 0 0;
  max-width: 650px;
}

/* ============ 错误条 ============ */
.error-state {
  align-items: center;
  background: #fff0eb;
  border-left: 3px solid var(--field-coral);
  border-radius: 4px;
  color: #9c4234;
  display: flex;
  flex: 0 0 auto;
  font-size: 13px;
  gap: 8px;
  line-height: 1.6;
  margin: 18px auto 0;
  max-width: 1420px;
  padding: 12px 14px;
  width: 100%;
}

/* ============ 主桌面三栏 ============ */
.assistant-desk {
  background: var(--field-white);
  border: 1px solid var(--field-line);
  border-radius: var(--travel-radius);
  box-shadow: var(--shadow-soft);
  display: grid;
  flex: 1 1 auto;
  grid-template-columns: 232px minmax(0, 1fr) 320px;
  margin: 18px auto 0;
  max-width: 1420px;
  min-height: 0;
  overflow: hidden;
  transition: opacity var(--motion-base) var(--ease-standard);
  width: 100%;
}

.assistant-desk.loading { opacity: 0.68; pointer-events: none; }

/* ============ 对话列表 ============ */
.conversation-rail {
  background: #f6fbf9;
  border-right: 1px solid var(--field-line);
  display: flex;
  flex-direction: column;
  min-height: 0;
  min-width: 0;
}

.rail-heading {
  align-items: flex-start;
  border-bottom: 1px solid var(--field-line);
  display: flex;
  gap: 12px;
  justify-content: space-between;
  padding: 20px 16px 16px;
}

.rail-heading h2,
.conversation-title h2,
.tool-heading h2,
.memory-heading h2 {
  color: var(--field-ink);
  font-family: Georgia, "Noto Serif SC", serif;
  font-size: 18px;
  font-weight: 600;
  letter-spacing: -0.01em;
  margin: 6px 0 0;
}

.rail-heading button {
  align-items: center;
  background: var(--field-teal);
  border: 0;
  border-radius: var(--travel-radius-sm);
  color: var(--field-white);
  cursor: pointer;
  display: inline-flex;
  flex: 0 0 34px;
  height: 34px;
  justify-content: center;
  transition: background-color var(--motion-base) var(--ease-standard),
              transform var(--motion-fast) var(--ease-standard),
              box-shadow var(--motion-base) var(--ease-standard);
}

.rail-heading button:hover {
  background: var(--field-deep);
  box-shadow: var(--shadow-soft);
  transform: translateY(-1px);
}

.rail-heading button:active { transform: scale(0.95); }

.rail-heading button:focus-visible {
  outline: 3px solid var(--field-saffron);
  outline-offset: 2px;
}

.conversation-list {
  align-content: start;
  display: grid;
  flex: 1 1 auto;
  min-height: 0;
  overflow: auto;
  padding: 8px;
  position: relative;
}

.conversation-row {
  align-items: stretch;
  border: 1px solid transparent;
  border-radius: var(--travel-radius-sm);
  display: flex;
  margin-bottom: 4px;
  overflow: hidden;
  transition: background-color var(--motion-base) var(--ease-standard),
              border-color var(--motion-base) var(--ease-standard);
}

.conversation-row:hover {
  background: var(--field-teal-soft);
  border-color: var(--field-line);
}

.conversation-row.active {
  background: var(--field-teal);
  border-color: var(--field-teal);
}

.conversation-item {
  background: transparent;
  border: 0;
  color: var(--field-ink);
  cursor: pointer;
  display: grid;
  flex: 1;
  gap: 6px;
  min-width: 0;
  padding: 12px 10px;
  text-align: left;
  transition: color var(--motion-base) var(--ease-standard);
}

.conversation-row.active .conversation-item { color: var(--field-white); }

.conversation-item strong {
  font-size: 13px;
  font-weight: 700;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.conversation-item span {
  color: var(--field-muted);
  font: 500 10px var(--field-mono);
  letter-spacing: 0.04em;
}

.conversation-row.active .conversation-item span { color: rgba(255, 255, 255, 0.78); }

.delete-conversation {
  align-items: center;
  background: transparent;
  border: 0;
  color: var(--field-muted);
  cursor: pointer;
  display: inline-flex;
  flex: 0 0 32px;
  justify-content: center;
  transition: background-color var(--motion-base) var(--ease-standard),
              color var(--motion-base) var(--ease-standard);
}

.conversation-row.active .delete-conversation { color: rgba(255, 255, 255, 0.78); }

.delete-conversation:hover:not(:disabled) {
  background: var(--field-coral);
  color: var(--field-white);
}

.delete-conversation:focus-visible {
  outline: 3px solid var(--field-saffron);
  outline-offset: -3px;
}

.delete-conversation:disabled { cursor: not-allowed; opacity: 0.5; }

.rail-empty {
  color: var(--field-muted);
  font-size: 12px;
  line-height: 1.55;
  margin: 14px 10px;
}

/* ============ 对话面板 ============ */
.conversation-panel {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr) auto;
  min-height: 0;
  min-width: 0;
}

.conversation-title {
  align-items: center;
  border-bottom: 1px solid var(--field-line);
  display: flex;
  gap: 14px;
  justify-content: space-between;
  min-height: 76px;
  padding: 14px 22px;
}

.conversation-title > div {
  align-items: center;
  display: flex;
  gap: 12px;
  min-width: 0;
}

.conversation-title > div > div {
  display: grid;
  gap: 2px;
  min-width: 0;
}

.conversation-title .section-label {
  color: var(--field-teal);
  margin: 0;
}

.assistant-mark {
  align-items: center;
  background: var(--field-teal-soft);
  border-radius: 50%;
  color: var(--field-teal);
  display: inline-flex;
  flex: 0 0 36px;
  height: 36px;
  justify-content: center;
  width: 36px;
}

.source-status {
  background: var(--field-teal-soft);
  border: 1px solid #b7d8ca;
  border-radius: 999px;
  color: var(--field-teal);
  flex: 0 0 auto;
  font: 700 11px var(--field-mono);
  letter-spacing: 0.04em;
  padding: 6px 12px;
}

/* ============ 消息流 ============ */
.message-stream {
  align-content: start;
  display: grid;
  gap: 22px;
  min-height: 0;
  overflow: auto;
  overscroll-behavior: contain;
  padding: 28px clamp(18px, 3vw, 42px);
  position: relative;
}

.empty-message {
  align-items: center;
  color: var(--field-muted);
  display: grid;
  gap: 8px;
  justify-items: center;
  min-height: 320px;
  padding: 44px 20px;
  text-align: center;
}

.empty-mark {
  align-items: center;
  background: var(--field-teal-soft);
  border-radius: 50%;
  color: var(--field-teal);
  display: inline-flex;
  height: 52px;
  justify-content: center;
  width: 52px;
}

.empty-message strong {
  color: var(--field-ink);
  font-family: Georgia, "Noto Serif SC", serif;
  font-size: 18px;
  font-weight: 600;
  margin-top: 8px;
}

.empty-message p {
  color: var(--field-muted);
  font-size: 13px;
  line-height: 1.6;
  margin: 0;
  max-width: 340px;
}

.message {
  display: grid;
  gap: 7px;
  max-width: min(78%, 650px);
}

.message.user { justify-self: end; }

.message .role {
  color: var(--field-muted);
  font: 800 10px var(--field-mono);
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.message.user .role { text-align: right; }

.message p {
  background: var(--field-white);
  border: 1px solid var(--field-line);
  border-radius: var(--travel-radius-sm);
  color: var(--field-ink);
  font-size: 14px;
  line-height: 1.7;
  margin: 0;
  padding: 14px 16px;
  white-space: pre-wrap;
  transition: border-color var(--motion-base) var(--ease-standard),
              box-shadow var(--motion-base) var(--ease-standard);
}

.message p:hover {
  border-color: var(--field-teal);
  box-shadow: var(--shadow-soft);
}

.message.user p {
  background: var(--field-teal-soft);
  border-color: #b7d8ca;
}

.message details {
  color: var(--field-ink-soft);
  font-size: 12px;
  line-height: 1.55;
}

.message summary {
  align-items: center;
  color: var(--field-teal);
  cursor: pointer;
  display: flex;
  gap: 6px;
  font-weight: 700;
  list-style: none;
  transition: color var(--motion-base) var(--ease-standard);
}

.message summary:hover { color: var(--field-deep); }

.message summary:focus-visible {
  outline: 3px solid var(--field-saffron);
  outline-offset: 2px;
  border-radius: 4px;
}

.message summary::-webkit-details-marker { display: none; }

.message ol {
  border-top: 1px solid var(--field-line);
  display: grid;
  gap: 10px;
  list-style: none;
  margin: 10px 0 0;
  padding: 10px 0 0 0;
}

.message li {
  display: grid;
  gap: 3px;
}

.message li strong {
  color: var(--field-ink);
  display: block;
  font-size: 11px;
  font-weight: 700;
}

.message li span {
  color: var(--field-ink-soft);
  font-size: 12px;
  line-height: 1.55;
}

/* ============ 输入区 ============ */
.ask-form {
  border-top: 1px solid var(--field-line);
  display: grid;
  gap: 10px;
  padding: 14px;
}

.ask-form textarea,
.plan-tool textarea,
.plan-tool select {
  background: var(--field-white);
  border: 1px solid var(--field-line);
  border-radius: var(--travel-radius-sm);
  color: var(--field-ink);
  font-size: 13px;
  line-height: 1.55;
  outline: 0;
  padding: 11px 12px;
  resize: vertical;
  transition: border-color var(--motion-base) var(--ease-standard),
              box-shadow var(--motion-base) var(--ease-standard);
  width: 100%;
}

.ask-form textarea { min-height: 82px; }

.ask-form textarea:hover,
.plan-tool textarea:hover,
.plan-tool select:hover { border-color: var(--field-teal); }

.ask-form textarea:focus,
.plan-tool textarea:focus,
.plan-tool select:focus {
  border-color: var(--field-teal);
  box-shadow: 0 0 0 3px var(--field-teal-soft);
  outline: 0;
}

.ask-form textarea:focus-visible,
.plan-tool textarea:focus-visible,
.plan-tool select:focus-visible {
  outline: 3px solid var(--field-saffron);
  outline-offset: 2px;
  box-shadow: none;
}

.compose-footer {
  align-items: center;
  display: flex;
  gap: 14px;
  justify-content: space-between;
}

.compose-footer > span {
  color: var(--field-muted);
  font-size: 11px;
  line-height: 1.5;
}

.ask-form button,
.plan-submit,
.modify-preview button {
  align-items: center;
  background: var(--field-teal);
  border: 1px solid var(--field-teal);
  border-radius: var(--travel-radius-sm);
  box-shadow: var(--shadow-soft);
  color: var(--field-white);
  cursor: pointer;
  display: inline-flex;
  font-size: 13px;
  font-weight: 700;
  gap: 10px;
  justify-content: space-between;
  min-height: 40px;
  padding: 9px 16px;
  transition: background-color var(--motion-base) var(--ease-standard),
              border-color var(--motion-base) var(--ease-standard),
              color var(--motion-base) var(--ease-standard),
              transform var(--motion-base) var(--ease-standard),
              box-shadow var(--motion-base) var(--ease-standard);
}

.ask-form button:hover:not(:disabled),
.plan-submit:hover:not(:disabled),
.modify-preview button:hover:not(:disabled) {
  background: var(--field-deep);
  border-color: var(--field-deep);
  box-shadow: var(--shadow-lift);
  transform: translateY(-2px);
}

.ask-form button:active:not(:disabled),
.plan-submit:active:not(:disabled),
.modify-preview button:active:not(:disabled) { transform: scale(0.98); }

.ask-form button:focus-visible,
.plan-submit:focus-visible,
.modify-preview button:focus-visible {
  outline: 3px solid var(--field-saffron);
  outline-offset: 3px;
}

.ask-form button:disabled,
.plan-submit:disabled,
.modify-preview button:disabled {
  cursor: not-allowed;
  opacity: 0.5;
  transform: none;
  box-shadow: none;
}

.ask-form button .spin {
  animation: spin 0.9s linear infinite;
}

/* ============ 上下文栏 ============ */
.context-rail {
  background: #f6fbf9;
  border-left: 1px solid var(--field-line);
  display: grid;
  align-content: start;
  min-height: 0;
  min-width: 0;
  overflow-y: auto;
}

.plan-tool,
.memory-panel { padding: 20px 18px; }

.plan-tool {
  display: grid;
  gap: 12px;
}

.tool-heading {
  border-bottom: 1px solid var(--field-line);
  padding-bottom: 14px;
}

.tool-heading .section-label { color: var(--field-coral); margin: 0; }

.tool-heading h2 { margin-top: 6px; }

.tool-heading p,
.memory-heading p {
  color: var(--field-muted);
  font-size: 12px;
  line-height: 1.55;
  margin: 8px 0 0;
}

.tool-heading small {
  color: var(--field-teal);
  display: inline-block;
  font-size: 11px;
  font-weight: 700;
  margin-top: 8px;
}

.plan-tool label {
  color: var(--field-ink-soft);
  display: grid;
  font-size: 11px;
  font-weight: 800;
  gap: 6px;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.plan-tool select { min-height: 40px; padding: 8px 10px; }

.plan-tool textarea { min-height: 94px; }

.plan-submit { justify-content: center; width: 100%; }

.planning-status {
  background: var(--field-teal-soft);
  border-left: 3px solid var(--field-teal);
  border-radius: 4px;
  color: var(--field-deep);
  font-size: 12px;
  line-height: 1.55;
  padding: 9px 12px;
}

.modify-preview {
  background: var(--field-white);
  border: 1px solid var(--field-line);
  border-radius: var(--travel-radius-sm);
  display: grid;
  gap: 10px;
  padding: 14px;
}

.modify-preview > div { display: grid; gap: 4px; }

.modify-preview strong {
  color: var(--field-ink);
  font-family: Georgia, "Noto Serif SC", serif;
  font-size: 14px;
  font-weight: 600;
}

.modify-preview span {
  color: var(--field-muted);
  font: 500 11px var(--field-mono);
  letter-spacing: 0.04em;
}

.modify-preview button { justify-content: center; width: 100%; }

.modify-preview a {
  color: var(--field-teal);
  display: inline-block;
  font-size: 12px;
  font-weight: 700;
  padding: 2px 0;
  text-decoration: none;
  transition: color var(--motion-base) var(--ease-standard);
}

.modify-preview a:hover { color: var(--field-deep); text-decoration: underline; }

.modify-preview a:focus-visible {
  outline: 3px solid var(--field-saffron);
  outline-offset: 2px;
  border-radius: 2px;
}

/* ============ 记忆面板 ============ */
.memory-panel { border-top: 1px solid var(--field-line); }

.memory-heading {
  border-bottom: 1px solid var(--field-line);
  padding-bottom: 14px;
}

.memory-heading .section-label { color: var(--field-coral); margin: 0; }

.memory-heading h2 { margin-top: 6px; }

.memory-heading > div:last-child {
  align-items: center;
  display: flex;
  gap: 8px;
  justify-content: space-between;
}

.memory-heading > div:last-child p { margin: 8px 0 0; }

.create-memory {
  align-items: center;
  background: var(--field-teal);
  border: 0;
  border-radius: var(--travel-radius-sm);
  color: var(--field-white);
  cursor: pointer;
  display: inline-flex;
  flex: 0 0 30px;
  height: 30px;
  justify-content: center;
}

.create-memory:hover { background: var(--field-deep); }

.empty-memory {
  color: var(--field-muted);
  font-size: 12px;
  line-height: 1.55;
  padding: 18px 0 4px;
}

.memory-item {
  border-bottom: 1px solid var(--field-line);
  padding: 14px 0;
  transition: background-color var(--motion-base) var(--ease-standard);
}

.memory-item:hover { background: var(--field-teal-soft); }

.memory-head {
  align-items: baseline;
  display: flex;
  gap: 8px;
  justify-content: space-between;
  padding: 0 6px;
}

.memory-item strong {
  color: var(--field-ink);
  font-size: 13px;
  font-weight: 700;
}

.memory-item > span,
.memory-head span {
  background: var(--field-teal-soft);
  border-radius: 999px;
  color: var(--field-teal);
  flex: 0 0 auto;
  font: 700 10px var(--field-mono);
  letter-spacing: 0.04em;
  padding: 3px 8px;
}

.memory-item p {
  color: var(--field-ink-soft);
  font: 500 12px/1.5 var(--field-mono);
  margin: 8px 6px;
  overflow-wrap: anywhere;
}

.memory-actions {
  display: flex;
  gap: 6px;
  justify-content: flex-end;
  padding: 0 6px;
}

.memory-actions button {
  align-items: center;
  background: transparent;
  border: 1px solid transparent;
  border-radius: var(--travel-radius-sm);
  color: var(--field-teal);
  cursor: pointer;
  display: inline-flex;
  font-size: 12px;
  font-weight: 700;
  min-height: 28px;
  min-width: 28px;
  padding: 4px 8px;
  transition: background-color var(--motion-base) var(--ease-standard),
              border-color var(--motion-base) var(--ease-standard),
              color var(--motion-base) var(--ease-standard);
}

.memory-actions button:hover {
  background: var(--field-teal);
  border-color: var(--field-teal);
  color: var(--field-white);
}

.memory-actions button:active { transform: scale(0.96); }

.memory-actions button:focus-visible {
  outline: 3px solid var(--field-saffron);
  outline-offset: 2px;
}

.memory-form-field {
  color: var(--field-ink-soft);
  display: grid;
  font-size: 13px;
  font-weight: 700;
  gap: 6px;
  margin-bottom: 16px;
}

.memory-form-field input,
.memory-form-field select,
.memory-form-field textarea {
  border: 1px solid var(--field-line);
  border-radius: var(--travel-radius-sm);
  color: var(--field-ink);
  font: inherit;
  padding: 9px 10px;
}

.memory-form-field textarea { min-height: 112px; resize: vertical; }

.memory-form-error { color: var(--field-coral); font-size: 13px; margin: -4px 0 12px; }

.memory-dialog-actions { display: flex; gap: 10px; justify-content: flex-end; }

.memory-dialog-actions button {
  border: 1px solid var(--field-teal);
  border-radius: var(--travel-radius-sm);
  cursor: pointer;
  font: inherit;
  padding: 8px 14px;
}

.memory-dialog-actions button:first-child { background: var(--field-white); color: var(--field-teal); }
.memory-dialog-actions button:last-child { background: var(--field-teal); color: var(--field-white); }
.memory-dialog-actions button:disabled { cursor: not-allowed; opacity: 0.5; }

/* ============ 焦点兜底 ============ */
button:focus-visible,
textarea:focus-visible,
select:focus-visible,
input:focus-visible,
a:focus-visible {
  outline: 3px solid var(--field-saffron);
  outline-offset: 3px;
}

/* ============ 响应式 ============ */
@media (max-width: 1120px) {
  .assistant-page { display: block; height: auto; min-height: calc(100vh - 72px); overflow: visible; padding: 32px clamp(18px, 4vw, 64px) 48px; }
  .assistant-desk { grid-template-columns: 210px minmax(0, 1fr); }
  .message-stream { max-height: 56vh; }
  .context-rail {
    border-left: 0;
    border-top: 1px solid var(--field-line);
    grid-column: 1 / -1;
    grid-template-columns: minmax(280px, 0.9fr) minmax(280px, 1.1fr);
    overflow-y: visible;
  }
  .memory-panel { border-left: 1px solid var(--field-line); border-top: 0; }
}

@media (max-width: 720px) {
  .assistant-page { padding: 28px 14px 48px; }
  .assistant-header { padding: 0 0 24px; }
  .assistant-header h1 { font-size: 30px; }
  .assistant-desk { grid-template-columns: 1fr; min-height: auto; }
  .conversation-rail { border-bottom: 1px solid var(--field-line); border-right: 0; max-width: 100%; }
  .rail-heading { align-items: center; }
  .conversation-list { display: flex; overflow: auto; padding: 8px; }
  .conversation-row { flex: 0 0 200px; margin-bottom: 0; margin-right: 6px; }
  .conversation-panel { min-height: 540px; }
  .conversation-title { padding: 14px; }
  .source-status { display: none; }
  .message-stream { min-height: 320px; padding: 20px 14px; }
  .message { max-width: 92%; }
  .compose-footer { align-items: stretch; flex-direction: column; gap: 8px; }
  .compose-footer > span { max-width: 100%; }
  .ask-form button { justify-content: center; width: 100%; }
  .context-rail { display: block; grid-column: auto; grid-template-columns: none; }
  .memory-panel { border-left: 0; border-top: 1px solid var(--field-line); }
  .plan-tool,
  .memory-panel { padding: 18px 14px; }
}

/* ============ 减少动效 ============ */
@media (prefers-reduced-motion: reduce) {
  .assistant-header,
  .assistant-desk,
  .conversation-row,
  .conversation-item,
  .delete-conversation,
  .rail-heading button,
  .message p,
  .message summary,
  .ask-form textarea,
  .plan-tool textarea,
  .plan-tool select,
  .ask-form button,
  .plan-submit,
  .modify-preview button,
  .modify-preview a,
   .memory-item,
   .memory-actions button,
   .create-memory,
   .memory-dialog-actions button {
    animation: none !important;
    transition: none !important;
  }
  .rail-heading button:hover,
  .ask-form button:hover:not(:disabled),
  .plan-submit:hover:not(:disabled),
  .modify-preview button:hover:not(:disabled) {
    transform: none !important;
  }
  .ask-form button .spin { animation: none !important; }
}
</style>
