<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Bookmark, Copy, Flag, Heart, LoaderCircle, LogIn, MapPin, MessageCircle, Route, Send } from 'lucide-vue-next'
import { api } from '@/services/api'
import { useAuthStore } from '@/stores/auth'
import FieldNoteTimeline from './components/FieldNoteTimeline.vue'
import { copyDestination, copyFieldNote, getFieldNote, resolveFieldNoteImage, routeMeta, type FieldNoteDetail } from './fieldNotesApi'
import type { CommunityComment } from './types'
import { useReveal } from '@/composables/useReveal'

const props = defineProps<{ postId: string }>()
const router = useRouter()
const route = useRoute()
const auth = useAuthStore()
const note = ref<FieldNoteDetail | null>(null)
const comments = ref<CommunityComment[]>([])
const loading = ref(true)
const unavailable = ref(false)
const error = ref('')
const commentError = ref('')
const actionError = ref('')
const commentDraft = ref('')
const busyAction = ref('')
const liked = ref(false)
const favorited = ref(false)
const coverUrl = ref('')
const galleryUrls = ref<Record<string, string>>({})
const root = ref<HTMLElement | null>(null)
useReveal(root)

const metadata = computed(() => note.value ? routeMeta(note.value.itinerary_snapshot) : { days: 0, stops: 0 })
const destination = computed(() => note.value?.city_code || note.value?.itinerary_snapshot.title || '路线档案')
const signedIn = computed(() => auth.isConsumerSession)

function releaseImages() {
  if (coverUrl.value) URL.revokeObjectURL(coverUrl.value)
  Object.values(galleryUrls.value).forEach((url) => URL.revokeObjectURL(url))
  coverUrl.value = ''
  galleryUrls.value = {}
}

async function loadImages(fieldNote: FieldNoteDetail) {
  releaseImages()
  const ids = [...new Set(fieldNote.media_ids)]
  const results = await Promise.allSettled(ids.map(async (id) => [id, await resolveFieldNoteImage(id)] as const))
  const loaded: Record<string, string> = {}
  for (const result of results) if (result.status === 'fulfilled') loaded[result.value[0]] = result.value[1]
  galleryUrls.value = loaded
  coverUrl.value = fieldNote.cover_media_id ? loaded[fieldNote.cover_media_id] ?? '' : ''
}

async function loadComments() {
  commentError.value = ''
  try {
    const { data } = await api.get<{ items: CommunityComment[] }>(`/posts/${props.postId}/comments`)
    comments.value = data.items
  } catch {
    commentError.value = '留言暂时无法读取。'
  }
}

async function loadNote() {
  loading.value = true
  unavailable.value = false
  error.value = ''
  try {
    const loaded = await getFieldNote(props.postId)
    note.value = loaded
    void loadImages(loaded)
    void loadComments()
  } catch (reason) {
    const status = (reason as { response?: { status?: number } })?.response?.status
    const code = (reason as { code?: string })?.code
    unavailable.value = status === 404 || code === 'NOT_FOUND'
    error.value = unavailable.value ? '' : reason instanceof Error ? reason.message : '路线档案暂时无法读取。'
  } finally {
    loading.value = false
  }
}

function goToLogin() {
  void router.push({ path: '/login', query: { redirect: route.fullPath } })
}

async function toggleInteraction(kind: 'like' | 'favorite') {
  if (!note.value || busyAction.value) return
  if (!signedIn.value) return goToLogin()
  const active = kind === 'like' ? liked.value : favorited.value
  busyAction.value = kind
  actionError.value = ''
  try {
    if (kind === 'like') {
      if (active) await api.delete(`/posts/${note.value.id}/reactions/like`)
      else await api.post(`/posts/${note.value.id}/reactions`, { reaction_type: 'like' })
      liked.value = !active
    } else {
      if (active) await api.delete(`/posts/${note.value.id}/favorites`)
      else await api.post(`/posts/${note.value.id}/favorites`)
      favorited.value = !active
    }
  } catch {
    actionError.value = '操作没有完成，请稍后重试。'
  } finally {
    busyAction.value = ''
  }
}

async function copyRoute() {
  if (!note.value || busyAction.value) return
  if (!signedIn.value) return goToLogin()
  busyAction.value = 'copy'
  actionError.value = ''
  try {
    const result = await copyFieldNote(note.value.id)
    await router.push(copyDestination(result))
  } catch (reason) {
    actionError.value = reason instanceof Error ? reason.message : '路线未能沿用，请重试。'
  } finally {
    busyAction.value = ''
  }
}

async function submitComment() {
  if (!note.value || !commentDraft.value.trim() || busyAction.value) return
  if (!signedIn.value) return goToLogin()
  busyAction.value = 'comment'
  commentError.value = ''
  try {
    const { data } = await api.post<CommunityComment>(`/posts/${note.value.id}/comments`, { body_text: commentDraft.value.trim() })
    comments.value.push(data)
    commentDraft.value = ''
  } catch {
    commentError.value = '留言没有发布，请稍后重试。'
  } finally {
    busyAction.value = ''
  }
}

async function reportNote() {
  if (!note.value || busyAction.value) return
  if (!signedIn.value) return goToLogin()
  busyAction.value = 'report'
  actionError.value = ''
  try {
    await api.post(`/posts/${note.value.id}/reports`, { reason_code: 'other', detail: 'Reader report' })
  } catch {
    actionError.value = '举报未能提交，请稍后重试。'
  } finally {
    busyAction.value = ''
  }
}

watch(() => props.postId, loadNote)
onMounted(loadNote)
onUnmounted(releaseImages)
</script>

<template>
  <main class="reader-page" aria-label="田野笔记详情" ref="root">
    <section v-if="loading" class="reader-state" aria-live="polite"><LoaderCircle :size="24" class="spin" /><p>正在打开路线档案</p></section>
    <section v-else-if="unavailable" class="reader-state unavailable"><p class="kicker">ARCHIVE UNAVAILABLE</p><h1>这份路线档案暂不可读</h1><RouterLink to="/community">回到田野笔记</RouterLink></section>
    <section v-else-if="error" class="reader-state unavailable" role="alert"><p class="kicker">READ ERROR</p><h1>{{ error }}</h1><button type="button" @click="loadNote">重试</button></section>
    <template v-else-if="note">
      <header class="reader-hero reveal" :style="{ '--reveal-index': 0 }">
        <div class="hero-photo" :class="{ fallback: !coverUrl }"><img v-if="coverUrl" :src="coverUrl" :alt="`${note.title} 的封面照片`" /><div v-else aria-hidden="true"><Route :size="58" /><span>FIELD ROUTE ARCHIVE</span></div></div>
        <div class="hero-copy"><p class="kicker"><MapPin :size="14" />{{ destination }}</p><h1>{{ note.title }}</h1><p class="route-facts"><span>{{ metadata.days }} 日路线</span><span>{{ metadata.stops }} 个停靠点</span><span>{{ note.copy_count }} 次沿用</span></p><p class="byline">记录者 / {{ note.author_id }}</p></div>
      </header>

      <div class="reader-layout">
        <article class="reader-content reveal" :style="{ '--reveal-index': 1 }">
          <section class="recap"><p class="section-label">FIELD RECAP</p><p>{{ note.recap_text || note.body_text }}</p></section>
          <section v-if="note.media_ids.length" class="gallery" aria-label="路线照片"><div v-for="(assetId, index) in note.media_ids" :key="assetId" class="gallery-item" :class="{ unavailable: !galleryUrls[assetId] }"><img v-if="galleryUrls[assetId]" :src="galleryUrls[assetId]" :alt="`${note.title} 路线照片 ${index + 1}`" /><span v-else aria-hidden="true">PHOTO / {{ String(index + 1).padStart(2, '0') }}</span></div></section>
          <FieldNoteTimeline :snapshot="note.itinerary_snapshot" />
          <section class="comments" aria-label="旅人留言"><header><div><p class="section-label">TRAVELERS' LOG</p><h2>旅人留言</h2></div><MessageCircle :size="22" /></header><p v-if="commentError" class="inline-error">{{ commentError }} <button type="button" @click="loadComments">重试</button></p><ol v-else-if="comments.length" class="comment-list"><li v-for="comment in comments" :key="comment.id"><strong>{{ comment.author_id }}</strong><time>{{ new Date(comment.created_at).toLocaleDateString('zh-CN') }}</time><p>{{ comment.body_text }}</p></li></ol><p v-else class="no-comments">还没有人留下路线补充。</p><div class="comment-form"><template v-if="signedIn"><label class="sr-only" for="comment">留下留言</label><textarea id="comment" v-model="commentDraft" rows="3" placeholder="补充你的行走经验" /><button type="button" :disabled="!commentDraft.trim() || busyAction === 'comment'" @click="submitComment"><Send :size="16" />发布留言</button></template><button v-else type="button" class="login-comment" @click="goToLogin"><LogIn :size="16" />登录后参与留言</button></div></section>
        </article>

        <aside class="action-column reveal" :style="{ '--reveal-index': 2 }" aria-label="路线操作"><button class="copy-button" type="button" :disabled="busyAction === 'copy'" @click="copyRoute"><Copy :size="18" />{{ busyAction === 'copy' ? '正在沿用' : '沿用这条路线' }}</button><div class="quick-actions"><button type="button" :aria-label="liked ? '取消喜欢' : '喜欢这篇笔记'" :title="liked ? '取消喜欢' : '喜欢'" :aria-pressed="liked" :disabled="Boolean(busyAction)" @click="toggleInteraction('like')"><Heart :size="18" :fill="liked ? 'currentColor' : 'none'" /></button><button type="button" :aria-label="favorited ? '取消收藏' : '收藏这篇笔记'" :title="favorited ? '取消收藏' : '收藏'" :aria-pressed="favorited" :disabled="Boolean(busyAction)" @click="toggleInteraction('favorite')"><Bookmark :size="18" :fill="favorited ? 'currentColor' : 'none'" /></button><button type="button" aria-label="举报笔记" title="举报" :disabled="Boolean(busyAction)" @click="reportNote"><Flag :size="18" /></button></div><Transition name="fade"><p v-if="actionError" class="action-error">{{ actionError }}</p></Transition><p class="action-note">沿用后会创建一份仅属于你的可编辑行程。</p></aside>
      </div>
      <div class="mobile-actions" aria-label="路线操作"><button class="copy-button" type="button" :disabled="busyAction === 'copy'" @click="copyRoute"><Copy :size="18" />{{ busyAction === 'copy' ? '正在沿用' : '沿用路线' }}</button><button type="button" :aria-label="liked ? '取消喜欢' : '喜欢'" :aria-pressed="liked" @click="toggleInteraction('like')"><Heart :size="18" :fill="liked ? 'currentColor' : 'none'" /></button><button type="button" :aria-label="favorited ? '取消收藏' : '收藏'" :aria-pressed="favorited" @click="toggleInteraction('favorite')"><Bookmark :size="18" :fill="favorited ? 'currentColor' : 'none'" /></button></div>
    </template>
  </main>
</template>

<style scoped>
/* ============ 页面容器 ============ */
.reader-page {
  color: var(--field-ink);
  margin: 0 auto;
  max-width: 1220px;
  padding: 36px 28px 96px;
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

/* ============ 状态：加载 / 不可用 / 错误 ============ */
.reader-state {
  align-items: center;
  display: flex;
  flex-direction: column;
  gap: 12px;
  justify-content: center;
  min-height: 55vh;
}

.reader-state p {
  color: var(--field-muted);
  font: 800 11px var(--field-mono);
  letter-spacing: .1em;
}

.reader-state .spin { color: var(--field-teal); }

.reader-state h1 {
  font-size: 32px;
  text-align: center;
}

.reader-state a,
.reader-state button {
  background: var(--field-teal);
  border: 0;
  border-radius: var(--travel-radius-sm);
  color: #fff;
  cursor: pointer;
  padding: 11px 14px;
  text-decoration: none;
  transition: background-color var(--motion-base) var(--ease-standard), transform var(--motion-fast) var(--ease-standard), box-shadow var(--motion-base) var(--ease-standard);
}

.reader-state a:hover,
.reader-state button:hover {
  background: var(--field-deep);
  transform: translateY(-2px);
  box-shadow: 0 6px 16px rgba(8, 126, 120, .24);
}

.reader-state a:active,
.reader-state button:active { transform: scale(0.97); }

.reader-state a:focus-visible,
.reader-state button:focus-visible {
  outline: 3px solid var(--field-saffron);
  outline-offset: 2px;
}

/* ============ Hero ============ */
.reader-hero {
  border-bottom: 2px solid var(--field-ink);
  display: grid;
  grid-template-columns: minmax(0, 1.3fr) minmax(280px, .85fr);
}

.hero-photo {
  aspect-ratio: 1.5;
  background: #dce7e3;
  overflow: hidden;
}

.hero-photo img {
  height: 100%;
  object-fit: cover;
  width: 100%;
}

.hero-photo.fallback > div {
  align-items: center;
  color: var(--field-teal);
  display: flex;
  flex-direction: column;
  font: 800 10px var(--field-mono);
  gap: 12px;
  height: 100%;
  justify-content: center;
  letter-spacing: .12em;
}

.hero-copy {
  align-self: end;
  padding: clamp(24px, 4vw, 54px);
}

.kicker,
.section-label {
  align-items: center;
  color: var(--field-teal);
  display: flex;
  font: 800 10px var(--field-mono);
  gap: 6px;
  letter-spacing: .13em;
  margin: 0;
}

.hero-copy h1 {
  font-size: clamp(36px, 4.5vw, 60px);
  line-height: 1.08;
  margin: 16px 0 22px;
}

.route-facts {
  border-bottom: 1px solid var(--field-line);
  border-top: 1px solid var(--field-line);
  display: flex;
  flex-wrap: wrap;
  font: 800 11px var(--field-mono);
  gap: 12px;
  line-height: 1.5;
  margin: 0;
  padding: 12px 0;
}

.route-facts span + span::before {
  color: var(--field-saffron);
  content: '•';
  margin-right: 12px;
}

.byline {
  color: var(--field-muted);
  font-size: 13px;
  margin: 16px 0 0;
}

/* ============ 主体布局 ============ */
.reader-layout {
  display: grid;
  gap: clamp(32px, 6vw, 76px);
  grid-template-columns: minmax(0, 1fr) 210px;
  padding-top: 42px;
}

.reader-content { min-width: 0; }

/* ============ 回顾 ============ */
.recap {
  border-left: 3px solid var(--field-teal);
  margin-bottom: 36px;
  padding-left: 18px;
}

.recap > p:last-child {
  color: var(--field-ink-soft);
  font-size: 17px;
  line-height: 1.85;
  margin: 8px 0 0;
}

/* ============ 图集 ============ */
.gallery {
  display: grid;
  gap: 12px;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  margin-bottom: 36px;
}

.gallery-item {
  aspect-ratio: 1.3;
  background: #dce7e3;
  border-radius: var(--travel-radius-sm);
  overflow: hidden;
  position: relative;
}

.gallery-item img {
  height: 100%;
  object-fit: cover;
  width: 100%;
  transition: transform var(--motion-slow) var(--ease-out);
}

.gallery-item:hover img { transform: scale(1.05); }

.gallery-item.unavailable {
  align-items: center;
  color: var(--field-ink-soft);
  display: flex;
  font: 800 10px var(--field-mono);
  justify-content: center;
  letter-spacing: .1em;
}

/* ============ 评论 ============ */
.comments {
  border-top: 1px solid var(--field-line);
  margin-top: 8px;
  padding-top: 28px;
}

.comments header {
  align-items: center;
  display: flex;
  justify-content: space-between;
  margin-bottom: 18px;
}

.comments header h2 {
  font-size: 24px;
  margin: 7px 0 0;
}

.comments header > svg { color: var(--field-coral); }

.inline-error {
  align-items: center;
  background: var(--field-white);
  border: 1px solid var(--field-line);
  border-left: 3px solid var(--field-coral);
  border-radius: var(--travel-radius-sm);
  color: var(--field-coral);
  display: flex;
  flex-wrap: wrap;
  font-size: 13px;
  gap: 10px;
  margin: 0 0 14px;
  padding: 12px 14px;
}

.inline-error button {
  background: transparent;
  border: 1px solid var(--field-coral);
  border-radius: var(--travel-radius-sm);
  color: var(--field-coral);
  cursor: pointer;
  font-size: 12px;
  font-weight: 800;
  margin-left: auto;
  padding: 6px 10px;
  transition: background-color var(--motion-base) var(--ease-standard), color var(--motion-base) var(--ease-standard);
}

.inline-error button:hover {
  background: var(--field-coral);
  color: #fff;
}

.inline-error button:active { transform: scale(0.97); }

.inline-error button:focus-visible {
  outline: 3px solid var(--field-saffron);
  outline-offset: 2px;
}

.comment-list {
  display: grid;
  gap: 0;
  list-style: none;
  margin: 0;
  padding: 0;
}

.comment-list li {
  border-bottom: 1px solid var(--field-line);
  padding: 16px 0;
}

.comment-list strong {
  font-size: 13px;
  margin-right: 10px;
}

.comment-list time {
  color: var(--field-muted);
  font: 700 11px var(--field-mono);
}

.comment-list p {
  color: var(--field-ink-soft);
  line-height: 1.65;
  margin: 7px 0 0;
}

.no-comments {
  color: var(--field-muted);
  font-size: 14px;
  margin: 0;
  padding: 8px 0;
}

/* ============ 评论表单 ============ */
.comment-form {
  display: grid;
  gap: 10px;
  margin-top: 20px;
}

.comment-form textarea {
  background: #fff;
  border: 1px solid var(--field-line);
  border-radius: var(--travel-radius-sm);
  color: var(--field-ink);
  font: inherit;
  line-height: 1.55;
  padding: 11px;
  resize: vertical;
  transition: border-color var(--motion-base) var(--ease-standard), box-shadow var(--motion-base) var(--ease-standard);
}

.comment-form textarea:focus {
  border-color: var(--field-teal);
  box-shadow: var(--shadow-focus);
  outline: 0;
}

.comment-form button {
  align-items: center;
  background: var(--field-teal);
  border: 0;
  border-radius: var(--travel-radius-sm);
  color: #fff;
  cursor: pointer;
  display: inline-flex;
  gap: 7px;
  justify-content: center;
  justify-self: end;
  min-height: 40px;
  padding: 0 16px;
  transition: background-color var(--motion-base) var(--ease-standard), transform var(--motion-fast) var(--ease-standard), box-shadow var(--motion-base) var(--ease-standard);
}

.comment-form button:hover:not(:disabled) {
  background: var(--field-deep);
  transform: translateY(-2px);
  box-shadow: 0 6px 16px rgba(8, 126, 120, .24);
}

.comment-form button:active:not(:disabled) { transform: scale(0.97); }

.comment-form button:focus-visible {
  outline: 3px solid var(--field-saffron);
  outline-offset: 2px;
}

.comment-form button:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}

.login-comment {
  align-items: center;
  background: transparent;
  border: 1px solid var(--field-teal);
  border-radius: var(--travel-radius-sm);
  color: var(--field-teal);
  cursor: pointer;
  display: inline-flex;
  font-weight: 800;
  gap: 8px;
  justify-self: start;
  min-height: 40px;
  padding: 0 16px;
  transition: background-color var(--motion-base) var(--ease-standard), color var(--motion-base) var(--ease-standard), transform var(--motion-fast) var(--ease-standard);
}

.login-comment:hover {
  background: var(--field-teal);
  color: #fff;
  transform: translateY(-2px);
}

.login-comment:active { transform: scale(0.97); }

.login-comment:focus-visible {
  outline: 3px solid var(--field-saffron);
  outline-offset: 2px;
}

/* ============ 操作列 ============ */
.action-column {
  display: grid;
  align-content: start;
  gap: 14px;
}

.copy-button {
  align-items: center;
  background: var(--field-teal);
  border: 0;
  border-radius: var(--travel-radius-sm);
  color: #fff;
  cursor: pointer;
  display: inline-flex;
  font-weight: 800;
  font-size: 14px;
  gap: 8px;
  justify-content: center;
  min-height: 44px;
  padding: 0 16px;
  width: 100%;
  transition: background-color var(--motion-base) var(--ease-standard), transform var(--motion-fast) var(--ease-standard), box-shadow var(--motion-base) var(--ease-standard);
}

.copy-button:hover:not(:disabled) {
  background: var(--field-deep);
  transform: translateY(-2px);
  box-shadow: 0 8px 20px rgba(8, 126, 120, .28);
}

.copy-button:active:not(:disabled) { transform: scale(0.98); }

.copy-button:focus-visible {
  outline: 3px solid var(--field-saffron);
  outline-offset: 2px;
}

.copy-button:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}

.quick-actions {
  display: grid;
  gap: 8px;
}

.quick-actions button {
  align-items: center;
  background: #fff;
  border: 1px solid var(--field-line);
  border-radius: var(--travel-radius-sm);
  color: var(--field-ink-soft);
  cursor: pointer;
  display: inline-flex;
  gap: 8px;
  justify-content: center;
  min-height: 42px;
  transition: border-color var(--motion-base) var(--ease-standard), color var(--motion-base) var(--ease-standard), background-color var(--motion-base) var(--ease-standard), transform var(--motion-fast) var(--ease-standard);
}

.quick-actions button:hover:not(:disabled) {
  border-color: var(--field-teal);
  color: var(--field-teal);
  transform: translateY(-2px);
}

.quick-actions button:active:not(:disabled) { transform: scale(0.97); }

.quick-actions button:focus-visible {
  outline: 3px solid var(--field-saffron);
  outline-offset: 2px;
}

.quick-actions button:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}

.quick-actions button[aria-pressed='true'] {
  background: var(--field-teal-soft);
  border-color: var(--field-teal);
  color: var(--field-teal);
}

.action-error {
  background: var(--field-white);
  border: 1px solid var(--field-line);
  border-left: 3px solid var(--field-coral);
  border-radius: var(--travel-radius-sm);
  color: var(--field-coral);
  font-size: 12px;
  line-height: 1.55;
  margin: 0;
  padding: 10px 12px;
}

.action-note {
  color: var(--field-muted);
  font-size: 12px;
  line-height: 1.55;
  margin: 0;
}

/* ============ 移动端固定操作栏 ============ */
.mobile-actions { display: none; }

/* ============ 响应式 ============ */
@media (max-width: 760px) {
  .reader-page { padding: 0 0 86px; }
  .reader-hero { grid-template-columns: 1fr; }
  .hero-photo { aspect-ratio: 1.32; }
  .hero-copy { padding: 28px 18px; }
  .reader-layout {
    display: block;
    padding: 32px 18px 0;
  }
  .action-column { display: none; }
  .gallery { margin-bottom: 36px; }
  .recap { margin-bottom: 35px; }
  .recap > p:last-child { font-size: 16px; }
  .comments { margin-top: 38px; }
  .mobile-actions {
    background: rgba(243, 247, 245, .96);
    border-top: 1px solid var(--field-line);
    bottom: 0;
    display: grid;
    gap: 7px;
    grid-template-columns: 1fr 44px 44px;
    left: 0;
    padding: 9px 14px;
    position: fixed;
    right: 0;
    z-index: 10;
    backdrop-filter: blur(12px);
  }
  .mobile-actions .copy-button { min-height: 42px; }
  .mobile-actions .copy-button:hover:not(:disabled) { transform: none; }
}

/* ============ 降级 ============ */
@media (prefers-reduced-motion: reduce) {
  .reader-state a,
  .reader-state button,
  .copy-button,
  .quick-actions button,
  .comment-form button,
  .login-comment,
  .inline-error button,
  .gallery-item img { transition: none; }
  .reader-state a:hover,
  .reader-state button:hover,
  .copy-button:hover:not(:disabled),
  .comment-form button:hover:not(:disabled),
  .login-comment:hover { transform: none; box-shadow: none; }
  .reader-state a:active,
  .reader-state button:active,
  .copy-button:active:not(:disabled),
  .quick-actions button:active:not(:disabled),
  .comment-form button:active:not(:disabled),
  .login-comment:active,
  .inline-error button:active { transform: none; }
  .quick-actions button:hover:not(:disabled) { transform: none; }
  .gallery-item:hover img { transform: none; }
}
</style>
