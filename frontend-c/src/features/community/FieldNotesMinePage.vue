<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { ArrowLeft, Clock3, FileText, RefreshCw } from 'lucide-vue-next'
import { listMyFieldNotes, type FieldNoteAuthorStatus } from './fieldNotesApi'
import { useReveal } from '@/composables/useReveal'

const notes = ref<FieldNoteAuthorStatus[]>([])
const state = ref<'loading' | 'ready' | 'error'>('loading')
const root = ref<HTMLElement | null>(null)
useReveal(root)

const statusText: Record<FieldNoteAuthorStatus['status'], string> = {
  draft: '草稿', pending_review: '审核中', published: '已发布', hidden: '已隐藏', rejected: '未通过',
}

async function load() {
  state.value = 'loading'
  try {
    notes.value = await listMyFieldNotes()
    state.value = 'ready'
  } catch {
    state.value = 'error'
  }
}

onMounted(() => void load())
</script>

<template>
  <main class="mine-page" ref="root">
    <header class="page-header" data-reveal>
      <RouterLink class="back" to="/community"><ArrowLeft :size="16" />田野笔记</RouterLink>
      <div><p>AUTHOR ARCHIVE</p><h1>我的田野笔记</h1></div>
    </header>

    <section v-if="state === 'loading'" class="state" aria-live="polite"><Clock3 :size="20" />正在读取你的投稿。</section>
    <section v-else-if="state === 'error'" class="state error" role="alert"><p>投稿记录暂时无法读取。</p><button type="button" @click="load"><RefreshCw :size="15" />重试</button></section>
    <section v-else-if="!notes.length" class="state empty"><FileText :size="24" /><h2>还没有田野笔记。</h2><p>从任一可编辑行程的发布入口提交一份路线记录。</p><RouterLink to="/itineraries">查看我的计划</RouterLink></section>
    <ol v-else class="notes reveal" aria-label="我的田野笔记">
      <li v-for="note in notes" :key="note.id">
        <div class="note-main"><p class="status" :class="note.status">{{ statusText[note.status] }}</p><h2>{{ note.title }}</h2><p class="recap">{{ note.recap_text }}</p><p v-if="note.moderation_reason" class="reason">审核说明：{{ note.moderation_reason }}</p></div>
        <RouterLink v-if="note.status === 'published'" :to="`/community/${note.id}`">查看公开笔记</RouterLink>
        <span v-else class="private">仅你可见</span>
      </li>
    </ol>
  </main>
</template>

<style scoped>
/* ============ 页面容器 ============ */
.mine-page {
  color: var(--field-ink);
  margin: 0 auto;
  max-width: 920px;
  min-height: calc(100vh - 70px);
  padding: 36px 20px 60px;
}

/* ============ 页头 ============ */
.page-header {
  border-bottom: 2px solid var(--field-ink);
  display: grid;
  gap: 22px;
  padding-bottom: 23px;
}

.back {
  align-items: center;
  color: var(--field-teal);
  display: inline-flex;
  font: 800 12px var(--field-mono);
  gap: 6px;
  text-decoration: none;
  width: fit-content;
  transition: color var(--motion-fast) var(--ease-standard), transform var(--motion-fast) var(--ease-standard);
}

.back:hover {
  color: var(--field-deep);
  transform: translateX(-3px);
}

.back:active { transform: scale(0.97); }

.back:focus-visible {
  outline: 3px solid var(--field-saffron);
  outline-offset: 3px;
  border-radius: var(--travel-radius-sm);
}

.page-header p {
  color: var(--field-teal);
  font: 800 10px var(--field-mono);
  letter-spacing: .1em;
  margin: 0 0 8px;
}

.page-header h1 {
  font-size: 34px;
  letter-spacing: 0;
  margin: 0;
}

/* ============ 状态条 ============ */
.state {
  align-items: center;
  border-bottom: 1px solid var(--field-line);
  color: var(--field-muted);
  display: flex;
  gap: 10px;
  justify-content: center;
  min-height: 220px;
  text-align: center;
}

.state.error {
  color: var(--field-coral);
  flex-direction: column;
}

.state button,
.state a {
  align-items: center;
  background: var(--field-deep);
  border: 0;
  border-radius: var(--travel-radius-sm);
  color: #fff;
  cursor: pointer;
  display: inline-flex;
  font: 800 12px var(--field-mono);
  gap: 6px;
  padding: 10px 13px;
  text-decoration: none;
  transition: background-color var(--motion-base) var(--ease-standard), transform var(--motion-fast) var(--ease-standard), box-shadow var(--motion-base) var(--ease-standard);
}

.state button:hover,
.state a:hover {
  background: var(--field-teal);
  transform: translateY(-2px);
  box-shadow: 0 6px 16px rgba(8, 126, 120, .24);
}

.state button:active,
.state a:active { transform: scale(0.97); }

.state button:focus-visible,
.state a:focus-visible {
  outline: 3px solid var(--field-saffron);
  outline-offset: 2px;
}

.state.empty { flex-direction: column; }

.state.empty h2,
.state.empty p { margin: 0; }

.state.empty svg { color: var(--field-muted); }

/* ============ 笔记列表 ============ */
.notes {
  list-style: none;
  margin: 0;
  padding: 0;
}

.notes li {
  align-items: center;
  border-bottom: 1px solid var(--field-line);
  display: flex;
  gap: 20px;
  justify-content: space-between;
  padding: 22px 0;
}

.note-main { min-width: 0; }

.status {
  font: 800 10px var(--field-mono);
  letter-spacing: .08em;
  margin: 0 0 8px;
}

.status.draft { color: var(--field-muted); }
.status.pending_review { color: var(--field-saffron); }
.status.published { color: var(--field-teal); }
.status.hidden,
.status.rejected { color: var(--field-coral); }

.note-main h2 {
  font-size: 20px;
  margin: 0;
}

.recap {
  color: var(--field-ink-soft);
  line-height: 1.55;
  margin: 8px 0 0;
}

.reason {
  color: var(--field-coral);
  font-size: 13px;
  margin: 8px 0 0;
}

.notes a {
  color: var(--field-teal);
  flex: 0 0 auto;
  font: 800 12px var(--field-mono);
  text-decoration: none;
  transition: color var(--motion-fast) var(--ease-standard), transform var(--motion-fast) var(--ease-standard);
}

.notes a:hover {
  color: var(--field-deep);
  transform: translateX(3px);
}

.notes a:active { transform: scale(0.97); }

.notes a:focus-visible {
  outline: 3px solid var(--field-saffron);
  outline-offset: 3px;
  border-radius: var(--travel-radius-sm);
}

.private {
  color: var(--field-muted);
  flex: 0 0 auto;
  font: 800 11px var(--field-mono);
}

/* ============ 降级 ============ */
@media (prefers-reduced-motion: reduce) {
  .back,
  .state button,
  .state a,
  .notes a { transition: none; }
  .back:hover,
  .state button:hover,
  .state a:hover,
  .notes a:hover { transform: none; box-shadow: none; }
  .back:active,
  .state button:active,
  .state a:active,
  .notes a:active { transform: none; }
}
</style>
