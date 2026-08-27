<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Bookmark, Heart, MessageCircle, Send } from 'lucide-vue-next'
import { api } from '@/services/api'
import CommunityFeed from './CommunityFeed.vue'
import PostEditor from './PostEditor.vue'
import type { CommunityPageResult, CommunityPost, SearchSource } from './types'

const posts = ref<CommunityPost[]>([])
const source = ref<SearchSource>('mysql')
const error = ref('')
const editing = ref(false)
const selectedPost = ref<CommunityPost | null>(null)
const comments = ref<{ id: string; author_id: string; body_text: string; parent_id: string | null; created_at: string }[]>([])
const commentDraft = ref('')
const interacting = ref(false)
const postDialogOpen = computed({ get: () => selectedPost.value !== null, set: (open: boolean) => { if (!open) selectedPost.value = null } })
async function loadPosts() { error.value = ''; try { const response = await api.get<CommunityPageResult>('/posts'); source.value = 'mysql'; posts.value = response.data.items } catch (reason) { error.value = reason instanceof Error ? reason.message : 'Could not load published posts. Retry.' } }
async function openPost(post: CommunityPost) { selectedPost.value = post; comments.value = []; try { const response = await api.get<{ items: typeof comments.value }>('/posts/' + post.id + '/comments'); comments.value = response.data.items } catch { error.value = '评论暂时无法读取。' } }
async function toggle(path: string, remove = false) { if (!selectedPost.value || interacting.value) return; interacting.value = true; try { if (remove) await api.delete(path); else await api.post(path) } catch { error.value = '操作没有完成，请稍后重试。' } finally { interacting.value = false } }
async function addComment() { if (!selectedPost.value || !commentDraft.value.trim() || interacting.value) return; interacting.value = true; try { const response = await api.post('/posts/' + selectedPost.value.id + '/comments', { body_text: commentDraft.value.trim() }); comments.value.push(response.data); commentDraft.value = '' } catch { error.value = '评论没有发布。' } finally { interacting.value = false } }
async function saveDraft(value: { title: string; body_text: string; city_code: string }) { try { await api.post('/posts', value); editing.value = false; await loadPosts() } catch (reason) { error.value = reason instanceof Error ? reason.message : 'The draft could not be saved.' } }
onMounted(loadPosts)
</script>

<template>
  <PostEditor v-if="editing" @cancel="editing = false" @submit="saveDraft" />
  <CommunityFeed v-else :posts="posts" :search-source="source" :error="error" @select="openPost" @write="editing = true" />
  <el-dialog v-model="postDialogOpen" class="post-dialog" width="min(760px, 94vw)" :show-close="true">
    <template #header>
      <div v-if="selectedPost" class="dialog-header">
        <span>{{ selectedPost.city_code || '旅行社区' }}</span>
        <h2>{{ selectedPost.title }}</h2>
      </div>
    </template>
    <template v-if="selectedPost">
      <p class="post-body">{{ selectedPost.body_text }}</p>
      <div class="post-actions">
        <button type="button" :disabled="interacting" @click="toggle('/posts/' + selectedPost.id + '/reactions', false)"><Heart :size="17" />点赞</button>
        <button type="button" :disabled="interacting" @click="toggle('/posts/' + selectedPost.id + '/favorites', false)"><Bookmark :size="17" />收藏</button>
        <button type="button" :disabled="interacting" @click="toggle('/posts/' + selectedPost.id + '/reactions/like', true)">取消点赞</button>
        <button type="button" :disabled="interacting" @click="toggle('/posts/' + selectedPost.id + '/favorites', true)">取消收藏</button>
      </div>
      <section class="comments">
        <header>
          <div><p>CONVERSATION</p><h3>旅人留言</h3></div>
          <MessageCircle :size="20" />
        </header>
        <TransitionGroup name="list" tag="div" class="comment-thread">
          <article v-for="comment in comments" :key="comment.id"><strong>{{ comment.author_id }}</strong><p>{{ comment.body_text }}</p></article>
        </TransitionGroup>
        <div class="comment-box">
          <el-input v-model="commentDraft" type="textarea" :rows="3" placeholder="留下一句回应" />
          <button type="button" :disabled="!commentDraft.trim() || interacting" @click="addComment"><Send :size="16" />发布</button>
        </div>
      </section>
    </template>
  </el-dialog>
</template>

<style scoped>
/* ============ 弹窗头部 ============ */
.dialog-header span,
.comments header p {
  color: var(--field-teal);
  font: 800 11px var(--field-mono);
  letter-spacing: .1em;
}

.dialog-header h2 {
  color: var(--field-ink);
  font-size: 30px;
  line-height: 1.25;
  margin: 10px 0 0;
}

/* ============ 正文 ============ */
.post-body {
  color: var(--field-ink-soft);
  font-size: 16px;
  line-height: 1.9;
  margin: 0;
  white-space: pre-wrap;
}

/* ============ 操作按钮 ============ */
.post-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin: 26px 0 34px;
}

.post-actions button {
  align-items: center;
  background: #fff;
  border: 1px solid var(--field-line);
  border-radius: var(--travel-radius-sm);
  color: var(--field-ink);
  cursor: pointer;
  display: inline-flex;
  font-size: 13px;
  gap: 6px;
  padding: 9px 12px;
  transition: border-color var(--motion-base) var(--ease-standard), color var(--motion-base) var(--ease-standard), background-color var(--motion-base) var(--ease-standard), transform var(--motion-fast) var(--ease-standard);
}

.post-actions button:first-child,
.post-actions button:nth-child(2) { color: var(--field-coral); }

.post-actions button:hover:not(:disabled) {
  border-color: var(--field-teal);
  color: var(--field-teal);
  transform: translateY(-2px);
}

.post-actions button:first-child:hover:not(:disabled),
.post-actions button:nth-child(2):hover:not(:disabled) {
  border-color: var(--field-coral);
  color: var(--field-coral);
}

.post-actions button:active:not(:disabled) { transform: scale(0.97); }

.post-actions button:focus-visible {
  outline: 3px solid var(--field-saffron);
  outline-offset: 2px;
}

.post-actions button:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}

/* ============ 评论区 ============ */
.comments {
  border-top: 1px solid var(--field-line);
  padding-top: 22px;
}

.comments header {
  align-items: center;
  display: flex;
  justify-content: space-between;
}

.comments header h3 {
  font-size: 20px;
  margin: 7px 0 0;
}

.comments header > svg { color: var(--field-coral); }

.comment-thread { display: grid; gap: 0; }

.comments article {
  border-bottom: 1px solid var(--field-line);
  padding: 16px 0;
}

.comments article strong { font-size: 13px; }

.comments article p {
  color: var(--field-ink-soft);
  line-height: 1.65;
  margin: 7px 0 0;
}

/* ============ 评论输入 ============ */
.comment-box {
  display: grid;
  gap: 10px;
  margin-top: 18px;
}

.comment-box button {
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
  min-height: 38px;
  padding: 0 13px;
  transition: background-color var(--motion-base) var(--ease-standard), transform var(--motion-fast) var(--ease-standard), box-shadow var(--motion-base) var(--ease-standard);
}

.comment-box button:hover:not(:disabled) {
  background: var(--field-deep);
  transform: translateY(-2px);
  box-shadow: 0 6px 16px rgba(8, 126, 120, .24);
}

.comment-box button:active:not(:disabled) { transform: scale(0.97); }

.comment-box button:focus-visible {
  outline: 3px solid var(--field-saffron);
  outline-offset: 2px;
}

.comment-box button:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}

/* ============ 弹窗容器 ============ */
.post-dialog :deep(.el-dialog) {
  border-top: 4px solid var(--field-coral);
  border-radius: var(--travel-radius);
}

.post-dialog :deep(.el-dialog__header) {
  margin-right: 0;
  padding: 28px 30px 16px;
}

.post-dialog :deep(.el-dialog__body) { padding: 18px 30px 30px; }

/* ============ 响应式 ============ */
@media (max-width: 600px) {
  .dialog-header h2 { font-size: 25px; }
  .post-dialog :deep(.el-dialog__header) { padding: 22px 20px 12px; }
  .post-dialog :deep(.el-dialog__body) { padding: 16px 20px 24px; }
  .comment-box button { justify-self: stretch; }
}

/* ============ 降级 ============ */
@media (prefers-reduced-motion: reduce) {
  .post-actions button,
  .comment-box button { transition: none; }
  .post-actions button:hover:not(:disabled),
  .comment-box button:hover:not(:disabled) { transform: none; box-shadow: none; }
  .post-actions button:active:not(:disabled),
  .comment-box button:active:not(:disabled) { transform: none; }
}
</style>
