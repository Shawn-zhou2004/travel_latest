<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { RefreshCw, Search, SlidersHorizontal } from 'lucide-vue-next'
import FieldNoteCard from './components/FieldNoteCard.vue'
import { listFieldNotes, type FieldNoteSort, type FieldNoteSummary } from './fieldNotesApi'
import { useReveal } from '@/composables/useReveal'

const notes = ref<FieldNoteSummary[]>([])
const keyword = ref('')
const cityCode = ref('')
const sort = ref<FieldNoteSort>('recommended')
const loading = ref(true)
const error = ref('')
const root = ref<HTMLElement | null>(null)
useReveal(root)

async function loadNotes() {
  loading.value = true
  error.value = ''
  try {
    const page = await listFieldNotes({ q: keyword.value.trim() || undefined, city_code: cityCode.value.trim() || undefined, sort: sort.value })
    notes.value = page.items
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '笔记档案暂时无法读取。'
  } finally {
    loading.value = false
  }
}

function resetFilters() {
  keyword.value = ''
  cityCode.value = ''
  sort.value = 'recommended'
  void loadNotes()
}

onMounted(loadNotes)
</script>

<template>
  <main class="archive-page" aria-label="田野笔记" ref="root">
    <header class="archive-heading" data-reveal>
      <div><p class="section-label">FIELD / TRAVEL ARCHIVE</p><h1>田野笔记</h1><p>经过验证的行走路线，留给下一位出发的人。</p></div>
      <div class="archive-stamp" aria-label="公开路线档案"><span>OPEN</span><strong>ROUTE<br />ARCHIVE</strong><small>01 / 田野采集</small></div>
    </header>

    <form class="filters" data-reveal @submit.prevent="loadNotes">
      <label><Search :size="17" /><span class="sr-only">关键词</span><input v-model="keyword" type="search" placeholder="搜索路线、标题或见闻" /></label>
      <label><span class="sr-only">目的地城市代码</span><input v-model="cityCode" type="text" placeholder="目的地城市代码" /></label>
      <fieldset><legend class="sr-only">排序方式</legend><button type="button" :class="{ active: sort === 'recommended' }" :aria-pressed="sort === 'recommended'" @click="sort = 'recommended'; loadNotes()">推荐</button><button type="button" :class="{ active: sort === 'latest' }" :aria-pressed="sort === 'latest'" @click="sort = 'latest'; loadNotes()">最新</button></fieldset>
      <button class="apply" type="submit"><SlidersHorizontal :size="16" />筛选</button>
    </form>

    <section v-if="loading" class="loading-archive" aria-live="polite"><span>正在整理路线档案</span><div v-for="index in 3" :key="index" class="skeleton" /></section>
    <section v-else-if="error" class="state-panel" role="alert"><p>档案读取失败</p><strong>{{ error }}</strong><button type="button" @click="loadNotes"><RefreshCw :size="16" />重试</button></section>
    <section v-else-if="!notes.length" class="state-panel"><p>没有匹配的路线记录</p><strong>尝试换一个目的地，或清除筛选条件。</strong><button type="button" @click="resetFilters">重置筛选</button></section>
    <section v-else class="archive-list" aria-label="田野笔记列表"><FieldNoteCard :note="notes[0]" featured :index="0" /><div class="section-rule"><span>MORE ROUTES</span></div><FieldNoteCard v-for="(note, index) in notes.slice(1)" :key="note.id" :note="note" :index="index + 1" /></section>
  </main>
</template>

<style scoped>
/* ============ 页面容器 ============ */
.archive-page {
  color: var(--field-ink);
  margin: 0 auto;
  max-width: 1180px;
  padding: 58px 28px 88px;
}

.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}

/* ============ 页头 ============ */
.archive-heading {
  align-items: end;
  border-bottom: 2px solid var(--field-ink);
  display: flex;
  justify-content: space-between;
  padding-bottom: 31px;
}

.section-label {
  color: var(--field-teal);
  font: 800 11px var(--field-mono);
  letter-spacing: .14em;
  margin: 0;
}

.archive-heading h1 {
  font-size: clamp(48px, 7vw, 80px);
  line-height: 1;
  margin: 14px 0;
}

.archive-heading > div > p:last-child {
  color: var(--field-ink-soft);
  margin: 0;
}

.archive-stamp {
  border: 1px solid var(--field-teal);
  color: var(--field-teal);
  display: grid;
  font: 800 10px var(--field-mono);
  gap: 5px;
  letter-spacing: .08em;
  min-width: 134px;
  padding: 10px;
  transform: rotate(-3deg);
  transition: transform var(--motion-base) var(--ease-out);
}

.archive-stamp:hover { transform: rotate(0deg); }

.archive-stamp span { color: var(--field-coral); }

.archive-stamp strong {
  font-size: 15px;
  line-height: 1.05;
}

.archive-stamp small {
  color: var(--field-muted);
  font-size: 8px;
}

/* ============ 筛选区 ============ */
.filters {
  align-items: stretch;
  border-bottom: 1px solid var(--field-line);
  display: grid;
  gap: 10px;
  grid-template-columns: minmax(180px, 1fr) 180px auto auto;
  padding: 18px 0;
}

.filters label {
  align-items: center;
  border: 1px solid var(--field-line);
  border-radius: var(--travel-radius-sm);
  display: flex;
  gap: 8px;
  padding: 0 11px;
  transition: border-color var(--motion-base) var(--ease-standard), box-shadow var(--motion-base) var(--ease-standard);
}

.filters label:focus-within {
  border-color: var(--field-teal);
  box-shadow: var(--shadow-focus);
}

.filters label svg {
  color: var(--field-teal);
  flex: 0 0 auto;
}

.filters input {
  background: transparent;
  border: 0;
  color: var(--field-ink);
  font: inherit;
  min-width: 0;
  outline: 0;
  padding: 11px 0;
  width: 100%;
}

.filters fieldset {
  border: 0;
  display: flex;
  margin: 0;
  padding: 0;
}

.filters button {
  background: transparent;
  border: 1px solid var(--field-line);
  color: var(--field-ink-soft);
  cursor: pointer;
  font: 800 12px var(--field-mono);
  padding: 0 12px;
  transition: background-color var(--motion-base) var(--ease-standard), border-color var(--motion-base) var(--ease-standard), color var(--motion-base) var(--ease-standard);
}

.filters fieldset button + button { border-left: 0; }

.filters button:hover:not(.active) {
  border-color: var(--field-teal);
  color: var(--field-teal);
}

.filters button.active {
  background: var(--field-teal);
  border-color: var(--field-teal);
  color: #fff;
}

.filters button:focus-visible {
  outline: 3px solid var(--field-saffron);
  outline-offset: 2px;
}

.filters .apply {
  align-items: center;
  background: var(--field-ink);
  border-color: var(--field-ink);
  border-radius: var(--travel-radius-sm);
  color: #fff;
  display: inline-flex;
  gap: 7px;
  justify-content: center;
  min-height: 42px;
}

.filters .apply:hover {
  background: var(--field-deep);
  border-color: var(--field-deep);
  transform: translateY(-2px);
  box-shadow: var(--shadow-soft);
}

.filters .apply:active { transform: scale(0.97); }

.filters .apply:focus-visible {
  outline: 3px solid var(--field-saffron);
  outline-offset: 2px;
}

/* ============ 状态：加载骨架 ============ */
.loading-archive {
  align-items: center;
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 48px 0;
}

.loading-archive span {
  color: var(--field-muted);
  font: 800 11px var(--field-mono);
  letter-spacing: .1em;
}

.loading-archive .skeleton {
  background: linear-gradient(90deg, var(--field-line) 25%, var(--field-paper) 50%, var(--field-line) 75%);
  background-size: 200% 100%;
  animation: shimmer 1.8s ease-in-out infinite;
  border: 1px solid var(--field-line);
  border-radius: var(--travel-radius);
  height: 120px;
  width: 100%;
}

@keyframes shimmer {
  0% { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}

/* ============ 状态：错误 / 空态 ============ */
.state-panel {
  align-items: center;
  background: var(--field-white);
  border: 1px solid var(--field-line);
  border-left: 3px solid var(--field-coral);
  border-radius: var(--travel-radius-sm);
  color: var(--field-ink-soft);
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-top: 32px;
  padding: 36px 24px;
  text-align: center;
}

.state-panel p {
  color: var(--field-muted);
  font: 800 11px var(--field-mono);
  letter-spacing: .1em;
  margin: 0;
}

.state-panel strong {
  color: var(--field-ink);
  font-size: 15px;
  font-weight: 600;
}

.state-panel button {
  align-items: center;
  background: var(--field-teal);
  border: 0;
  border-radius: var(--travel-radius-sm);
  color: #fff;
  cursor: pointer;
  display: inline-flex;
  gap: 6px;
  margin-top: 8px;
  min-height: 38px;
  padding: 0 16px;
  transition: background-color var(--motion-base) var(--ease-standard), transform var(--motion-fast) var(--ease-standard), box-shadow var(--motion-base) var(--ease-standard);
}

.state-panel button:hover {
  background: var(--field-deep);
  transform: translateY(-2px);
  box-shadow: 0 6px 16px rgba(8, 126, 120, .24);
}

.state-panel button:active { transform: scale(0.97); }

.state-panel button:focus-visible {
  outline: 3px solid var(--field-saffron);
  outline-offset: 2px;
}

/* ============ 列表 ============ */
.archive-list {
  border-top: 1px solid var(--field-line);
  margin-top: 36px;
}

.section-rule {
  align-items: center;
  display: flex;
  gap: 14px;
  padding: 30px 0;
}

.section-rule::before,
.section-rule::after {
  background: var(--field-line);
  content: '';
  flex: 1;
  height: 1px;
}

.section-rule span {
  color: var(--field-muted);
  font: 800 10px var(--field-mono);
  letter-spacing: .14em;
}

/* ============ 响应式 ============ */
@media (max-width: 680px) {
  .archive-page { padding: 36px 18px 70px; }
  .archive-heading {
    align-items: start;
    gap: 18px;
  }
  .archive-heading h1 { font-size: 52px; }
  .archive-stamp { min-width: 102px; }
  .filters { grid-template-columns: 1fr 1fr; }
  .filters label:first-child { grid-column: 1 / -1; }
  .filters .apply { min-height: 42px; }
  .filters fieldset button { flex: 1; }
  .filters fieldset { width: 100%; }
}

/* ============ 降级 ============ */
@media (prefers-reduced-motion: reduce) {
  .loading-archive .skeleton { animation: none; }
  .archive-stamp { transform: none; }
  .archive-stamp:hover { transform: none; }
  .filters label,
  .filters button,
  .filters .apply,
  .state-panel button { transition: none; }
  .filters .apply:hover,
  .state-panel button:hover { transform: none; box-shadow: none; }
  .filters .apply:active,
  .state-panel button:active { transform: none; }
}
</style>
