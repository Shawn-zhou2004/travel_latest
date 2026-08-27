<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import { ArrowRight, Sparkles, Trash2, X } from 'lucide-vue-next'
import { useAuthStore } from '@/stores/auth'
import { normalizeApiError } from '@/services/api'
import { deleteItinerary, listItineraries, type ItineraryRecord } from '../api'
import { generationJobStatusLabels, listPendingGenerationPreviews, type GenerationJobResponse } from '../aiPlanningApi'
import { useReveal } from '@/composables/useReveal'

const auth = useAuthStore()
const router = useRouter()
const itineraries = ref<ItineraryRecord[]>([])
const pendingPreviews = ref<GenerationJobResponse[]>([])
const loading = ref(true)
const error = ref('')
const deletingItinerary = ref<ItineraryRecord | null>(null)
const deleting = ref(false)
const deleteError = ref('')
const root = ref<HTMLElement | null>(null)
useReveal(root)

onMounted(async () => {
  try {
    itineraries.value = await listItineraries()
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : 'Itineraries could not be loaded.'
  } finally {
    loading.value = false
  }
  try {
    pendingPreviews.value = await listPendingGenerationPreviews()
  } catch {
    // The pending-preview entry is a convenience; its failure must not block the saved-itinerary list.
  }
})

function confirmPending(jobId: string) {
  router.push({ path: '/plan', query: { jobId } })
}

function formatPendingDate(value: string) {
  return value.slice(0, 10)
}

function isOwner(itinerary: ItineraryRecord) {
  return itinerary.access_role === 'owner' || itinerary.owner_id === auth.user?.id
}

function openDelete(itinerary: ItineraryRecord) {
  deletingItinerary.value = itinerary
  deleteError.value = ''
}

function closeDelete() {
  if (deleting.value) return
  deletingItinerary.value = null
  deleteError.value = ''
}

async function confirmDelete() {
  const itinerary = deletingItinerary.value
  if (!itinerary || deleting.value) return
  deleting.value = true
  deleteError.value = ''
  try {
    await deleteItinerary(itinerary.id)
    itineraries.value = itineraries.value.filter((item) => item.id !== itinerary.id)
    deletingItinerary.value = null
  } catch (reason) {
    const apiError = normalizeApiError(reason)
    deleteError.value = apiError.code === 'COMPANION_PLAN_ACTIVE'
      ? '请先结束或取消同行计划后再删除行程。'
      : apiError.message
  } finally {
    deleting.value = false
  }
}
</script>

<template>
  <main class="itineraries-page" ref="root">
    <header class="page-header">
      <div class="page-header__intro">
        <p class="eyebrow">My travel plans</p>
        <h1>Itineraries</h1>
        <p class="lead">已保存的行程会按最近编辑顺序排列，点击进入即可继续编排日程。</p>
      </div>
      <RouterLink class="primary-action" to="/plan">New itinerary</RouterLink>
    </header>
    <section v-if="pendingPreviews.length" class="pending" aria-label="待确认的 AI 行程方案" data-reveal>
      <div class="pending-head">
        <p class="eyebrow">AI previews awaiting confirmation</p>
        <h2>待确认的 AI 行程方案</h2>
        <p>智能规划已为你生成这些方案，确认后写入你的行程。</p>
      </div>
      <div class="pending-list">
        <button v-for="pending in pendingPreviews" :key="pending.id" class="pending-card" type="button" @click="confirmPending(pending.id)">
          <span class="pending-icon"><Sparkles :size="18" /></span>
          <span class="pending-text">
            <strong>AI 智能规划方案</strong>
            <small>生成于 {{ formatPendingDate(pending.created_at) }} · {{ generationJobStatusLabels[pending.status] }}</small>
          </span>
          <span class="pending-cta">去确认 <ArrowRight :size="15" /></span>
        </button>
      </div>
    </section>
    <p v-if="loading" class="state state--loading" role="status" aria-live="polite">Loading your itineraries.</p>
    <p v-else-if="error" class="state state--error" role="alert">{{ error }}</p>
    <section v-else-if="itineraries.length" class="list" aria-label="Saved itineraries" data-reveal>
      <TransitionGroup name="list">
        <article v-for="(itinerary, index) in itineraries" :key="itinerary.id" class="item" :style="{ '--reveal-index': index }">
          <RouterLink class="item-link" :to="`/itineraries/${itinerary.id}`">
            <span class="item-text">
              <strong>{{ itinerary.title }}</strong>
              <small>{{ itinerary.start_date }} to {{ itinerary.end_date }}</small>
            </span>
            <span class="version">v{{ itinerary.version }}</span>
          </RouterLink>
          <button v-if="isOwner(itinerary)" class="delete-action" type="button" title="删除计划" aria-label="删除计划" @click.stop="openDelete(itinerary)"><Trash2 :size="17" /></button>
        </article>
      </TransitionGroup>
    </section>
    <section v-else class="empty" data-reveal>
      <strong>No itinerary yet</strong>
      <p>Start with a date range and build the days in your own order.</p>
      <RouterLink class="primary-action" to="/plan">Create your first itinerary</RouterLink>
    </section>
    <Transition name="fade">
      <div v-if="deletingItinerary" class="delete-overlay" role="dialog" aria-modal="true" aria-labelledby="delete-itinerary-title">
        <section class="delete-dialog">
          <header>
            <div>
              <p class="eyebrow">PERMANENT DELETE</p>
              <h2 id="delete-itinerary-title">删除计划</h2>
            </div>
            <button type="button" title="关闭" aria-label="关闭" :disabled="deleting" @click="closeDelete"><X :size="18" /></button>
          </header>
          <p>此操作会永久删除“{{ deletingItinerary.title }}”及其所有路线内容，且无法撤销。请确认是否继续。</p>
          <Transition name="slide-down">
            <p v-if="deleteError" class="delete-error" role="alert">{{ deleteError }}</p>
          </Transition>
          <footer>
            <button type="button" :disabled="deleting" @click="closeDelete">取消</button>
            <button class="delete-confirm" type="button" :disabled="deleting" @click="confirmDelete">{{ deleting ? '正在删除' : '永久删除' }}</button>
          </footer>
        </section>
      </div>
    </Transition>
  </main>
</template>

<style scoped>
/* ============ 页面容器 ============ */
.itineraries-page {
  color: var(--field-ink);
  margin: 0 auto;
  max-width: 920px;
  min-height: calc(100vh - 70px);
  padding: 48px 24px 80px;
}

/* ============ 页头 ============ */
.page-header {
  align-items: flex-end;
  border-bottom: 2px solid transparent;
  border-image: linear-gradient(90deg, var(--field-teal), var(--field-coral) 60%, transparent) 1;
  display: flex;
  gap: 24px;
  justify-content: space-between;
  padding-bottom: 28px;
  animation: header-enter var(--motion-slow) var(--ease-out) both;
}

@keyframes header-enter {
  from { opacity: 0; transform: translateY(-10px); }
  to { opacity: 1; transform: translateY(0); }
}

.page-header__intro { min-width: 0; }

.eyebrow {
  color: var(--field-teal);
  font: 800 11px var(--field-mono);
  letter-spacing: 0.12em;
  margin: 0 0 10px;
  text-transform: uppercase;
}

.page-header h1 {
  font-family: Georgia, "Noto Serif SC", serif;
  font-size: clamp(36px, 5vw, 56px);
  font-weight: 600;
  letter-spacing: -0.01em;
  line-height: 1.1;
  margin: 0;
}

.lead {
  color: var(--field-ink-soft);
  font-size: 14px;
  line-height: 1.65;
  margin: 12px 0 0;
  max-width: 520px;
}

/* ============ 主操作按钮 ============ */
.primary-action {
  align-items: center;
  background: var(--field-teal);
  border-radius: var(--travel-radius-sm);
  box-shadow: var(--shadow-soft);
  color: var(--field-white);
  display: inline-flex;
  font-weight: 700;
  font-size: 14px;
  flex: 0 0 auto;
  gap: 6px;
  justify-content: center;
  min-height: 44px;
  padding: 0 22px;
  text-decoration: none;
  transition: background-color var(--motion-base) var(--ease-standard),
              transform var(--motion-base) var(--ease-standard),
              box-shadow var(--motion-base) var(--ease-standard);
}

.primary-action:hover {
  background: var(--field-deep);
  box-shadow: var(--shadow-lift);
  transform: translateY(-2px);
}

.primary-action:active { transform: translateY(0) scale(0.98); }

.primary-action:focus-visible {
  outline: 3px solid var(--field-saffron);
  outline-offset: 3px;
}

/* ============ 状态条 ============ */
.state {
  align-items: center;
  background: var(--field-white);
  border: 1px solid var(--field-line);
  border-radius: var(--travel-radius-sm);
  display: flex;
  gap: 10px;
  margin-top: 28px;
  padding: 18px 22px;
}

.state--loading {
  border-left: 3px solid var(--field-teal);
  color: var(--field-ink-soft);
}

.state--error {
  border-color: var(--field-coral);
  border-left: 3px solid var(--field-coral);
  color: #9c4234;
}

/* ============ 列表 ============ */
.list {
  display: grid;
  gap: 14px;
  margin-top: 32px;
  position: relative;
}

.item {
  align-items: center;
  background: var(--field-white);
  border: 1px solid var(--field-line);
  border-radius: var(--travel-radius);
  display: flex;
  gap: 16px;
  padding: 20px 22px;
  position: relative;
  transition: border-color var(--motion-base) var(--ease-standard),
              box-shadow var(--motion-base) var(--ease-standard),
              transform var(--motion-base) var(--ease-standard);
}

.item::before {
  content: '';
  position: absolute;
  left: 0; top: 0; bottom: 0;
  width: 3px;
  background: var(--field-teal);
  border-radius: 3px 0 0 3px;
  transform: scaleY(0);
  transform-origin: bottom;
  transition: transform var(--motion-base) var(--ease-standard);
}

.item:hover {
  border-color: var(--field-teal);
  box-shadow: var(--shadow-lift);
  transform: translateY(-2px);
}

.item:hover::before { transform: scaleY(1); transform-origin: top; }

.item-link {
  align-items: center;
  color: inherit;
  display: flex;
  flex: 1;
  gap: 16px;
  justify-content: space-between;
  min-width: 0;
  text-decoration: none;
}

.item-link:focus-visible {
  outline: 3px solid var(--field-saffron);
  outline-offset: 3px;
  border-radius: var(--travel-radius-sm);
}

.item-text { display: grid; gap: 6px; min-width: 0; }

.item-text strong {
  color: var(--field-ink);
  font-family: Georgia, "Noto Serif SC", serif;
  font-size: 22px;
  font-weight: 600;
  line-height: 1.2;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  transition: color var(--motion-base) var(--ease-standard);
}

.item:hover .item-text strong { color: var(--field-teal); }

.item-text small {
  color: var(--field-muted);
  font: 500 12px var(--field-mono);
}

.version {
  background: var(--field-teal-soft);
  border-radius: 999px;
  color: var(--field-teal);
  flex: 0 0 auto;
  font: 700 11px var(--field-mono);
  letter-spacing: 0.04em;
  padding: 6px 10px;
  transition: background-color var(--motion-base) var(--ease-standard),
              color var(--motion-base) var(--ease-standard);
}

.item:hover .version {
  background: var(--field-teal);
  color: var(--field-white);
}

/* ============ 删除按钮 ============ */
.delete-action {
  align-items: center;
  background: var(--field-white);
  border: 1px solid var(--field-line);
  border-radius: 50%;
  color: var(--field-muted);
  cursor: pointer;
  display: inline-flex;
  flex: 0 0 38px;
  height: 38px;
  justify-content: center;
  transition: background-color var(--motion-base) var(--ease-standard),
              border-color var(--motion-base) var(--ease-standard),
              color var(--motion-base) var(--ease-standard),
              transform var(--motion-base) var(--ease-standard);
  width: 38px;
}

.delete-action:hover {
  background: #fff0eb;
  border-color: var(--field-coral);
  color: var(--field-coral);
  transform: scale(1.05);
}

.delete-action:active { transform: scale(0.95); }

.delete-action:focus-visible {
  outline: 3px solid var(--field-saffron);
  outline-offset: 3px;
}

/* ============ 待确认的 AI 行程方案 ============ */
.pending {
  background: linear-gradient(180deg, var(--field-paper), var(--field-white));
  border: 1px solid #f0d6cc;
  border-radius: var(--travel-radius);
  margin-top: 32px;
  padding: 24px 26px 26px;
}

.pending-head p { margin: 0 0 8px; }

.pending-head .eyebrow { color: var(--field-coral); }

.pending-head h2 {
  color: var(--field-ink);
  font-family: Georgia, "Noto Serif SC", serif;
  font-size: 24px;
  font-weight: 600;
  margin: 0 0 8px;
}

.pending-head > p:last-child {
  color: var(--field-ink-soft);
  font-size: 14px;
  line-height: 1.6;
  margin: 0;
  max-width: 520px;
}

.pending-list { display: grid; gap: 12px; margin-top: 18px; }

.pending-card {
  align-items: center;
  background: var(--field-white);
  border: 1px solid var(--field-line);
  border-radius: var(--travel-radius-sm);
  color: inherit;
  cursor: pointer;
  display: flex;
  gap: 14px;
  padding: 16px 18px;
  text-align: left;
  transition: border-color var(--motion-base) var(--ease-standard),
              box-shadow var(--motion-base) var(--ease-standard),
              transform var(--motion-base) var(--ease-standard);
  width: 100%;
}

.pending-card:hover {
  border-color: var(--field-coral);
  box-shadow: var(--shadow-lift);
  transform: translateY(-2px);
}

.pending-card:focus-visible {
  outline: 3px solid var(--field-saffron);
  outline-offset: 3px;
}

.pending-icon {
  align-items: center;
  background: #fff0eb;
  border-radius: 50%;
  color: var(--field-coral);
  display: inline-flex;
  flex: 0 0 40px;
  height: 40px;
  justify-content: center;
}

.pending-text { display: grid; flex: 1; gap: 5px; min-width: 0; }

.pending-text strong {
  color: var(--field-ink);
  font-family: Georgia, "Noto Serif SC", serif;
  font-size: 17px;
  font-weight: 600;
}

.pending-text small { color: var(--field-muted); font: 500 12px var(--field-mono); }

.pending-cta {
  align-items: center;
  color: var(--field-coral);
  display: inline-flex;
  flex: 0 0 auto;
  font-weight: 700;
  font-size: 13px;
  gap: 4px;
}

/* ============ 空态 ============ */
.empty {
  background: var(--field-white);
  border: 1px dashed var(--field-line);
  border-radius: var(--travel-radius);
  display: grid;
  gap: 8px;
  margin-top: 32px;
  padding: 36px 28px;
}

.empty strong {
  color: var(--field-ink);
  font-family: Georgia, "Noto Serif SC", serif;
  font-size: 22px;
  font-weight: 600;
}

.empty p {
  color: var(--field-ink-soft);
  font-size: 14px;
  line-height: 1.65;
  margin: 0 0 14px;
  max-width: 460px;
}

.empty .primary-action { justify-self: start; }

/* ============ 删除弹窗 ============ */
.delete-overlay {
  align-items: center;
  background: rgba(19, 43, 58, 0.48);
  display: flex;
  inset: 0;
  justify-content: center;
  padding: 20px;
  position: fixed;
  z-index: 60;
}

.delete-dialog {
  background: var(--field-white);
  border-radius: var(--travel-radius);
  box-shadow: 0 24px 60px rgba(19, 43, 58, 0.28);
  display: grid;
  gap: 18px;
  max-width: 520px;
  padding: 28px;
  width: min(100%, 520px);
}

.delete-dialog header {
  align-items: flex-start;
  display: flex;
  gap: 16px;
  justify-content: space-between;
}

.delete-dialog header > div { min-width: 0; }

.delete-dialog h2 {
  color: var(--field-ink);
  font-family: Georgia, "Noto Serif SC", serif;
  font-size: 22px;
  font-weight: 600;
  margin: 0;
}

.delete-dialog header button {
  align-items: center;
  background: transparent;
  border: 1px solid var(--field-line);
  border-radius: 50%;
  color: var(--field-muted);
  cursor: pointer;
  display: inline-flex;
  flex: 0 0 34px;
  height: 34px;
  justify-content: center;
  transition: background-color var(--motion-base) var(--ease-standard),
              color var(--motion-base) var(--ease-standard),
              border-color var(--motion-base) var(--ease-standard);
  width: 34px;
}

.delete-dialog header button:hover:not(:disabled) {
  background: var(--field-paper);
  border-color: var(--field-teal);
  color: var(--field-teal);
}

.delete-dialog header button:disabled { cursor: not-allowed; opacity: 0.5; }

.delete-dialog header button:focus-visible {
  outline: 3px solid var(--field-saffron);
  outline-offset: 3px;
}

.delete-dialog > p {
  color: var(--field-ink-soft);
  font-size: 14px;
  line-height: 1.65;
  margin: 0;
}

.delete-error {
  background: #fff0eb;
  border-left: 3px solid var(--field-coral);
  border-radius: 4px;
  color: #9c4234;
  font-size: 13px;
  line-height: 1.55;
  margin: 0;
  padding: 10px 12px;
}

.delete-dialog footer {
  display: flex;
  gap: 10px;
  justify-content: flex-end;
}

.delete-dialog footer button {
  align-items: center;
  background: transparent;
  border: 1px solid var(--field-line);
  border-radius: var(--travel-radius-sm);
  color: var(--field-ink-soft);
  cursor: pointer;
  display: inline-flex;
  font-weight: 700;
  font-size: 13px;
  gap: 6px;
  justify-content: center;
  min-height: 40px;
  padding: 0 18px;
  transition: background-color var(--motion-base) var(--ease-standard),
              border-color var(--motion-base) var(--ease-standard),
              color var(--motion-base) var(--ease-standard),
              transform var(--motion-base) var(--ease-standard);
}

.delete-dialog footer button:hover:not(:disabled) {
  background: var(--field-paper);
  border-color: var(--field-ink-soft);
  color: var(--field-ink);
}

.delete-dialog footer button:active:not(:disabled) { transform: scale(0.97); }

.delete-dialog footer button:focus-visible {
  outline: 3px solid var(--field-saffron);
  outline-offset: 3px;
}

.delete-dialog footer button:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}

.delete-confirm {
  background: var(--field-coral) !important;
  border-color: var(--field-coral) !important;
  color: var(--field-white) !important;
}

.delete-confirm:hover:not(:disabled) {
  background: #c25a45 !important;
  border-color: #c25a45 !important;
  color: var(--field-white) !important;
}

/* ============ 焦点光晕（全局兜底已存在，这里仅补遗漏） ============ */
a:focus-visible { outline: 3px solid var(--field-saffron); outline-offset: 3px; }

/* ============ 响应式 ============ */
@media (max-width: 640px) {
  .itineraries-page { padding: 36px 16px 64px; }
  .page-header { align-items: stretch; flex-direction: column; gap: 18px; }
  .primary-action { width: 100%; }
  .item { align-items: flex-start; flex-direction: column; gap: 14px; padding: 18px; }
  .item-link { width: 100%; }
  .version { align-self: flex-start; }
  .delete-action { align-self: flex-end; margin-top: -52px; }
  .pending { padding: 20px 18px 22px; }
  .pending-card { align-items: flex-start; flex-wrap: wrap; gap: 12px; padding: 16px; }
  .pending-card .pending-text strong { font-size: 16px; }
  .pending-cta { margin-left: 54px; }
  .delete-dialog footer { flex-direction: column-reverse; }
  .delete-dialog footer button { width: 100%; }
}

/* ============ 减少动效 ============ */
@media (prefers-reduced-motion: reduce) {
  .page-header,
  .item,
  .item::before,
  .pending-card,
  .primary-action,
  .delete-action,
  .delete-dialog footer button,
  .delete-dialog header button {
    animation: none !important;
    transition: none !important;
  }
  .item:hover,
  .pending-card:hover,
  .primary-action:hover,
  .delete-action:hover {
    transform: none !important;
  }
}
</style>
