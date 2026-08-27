<script setup lang="ts">
import { computed } from 'vue'
import { ArrowUpRight, Bookmark, MessageCircle, PenLine } from 'lucide-vue-next'
import type { CommunityPost, SearchSource } from './types'
import { feedStateMessage } from './types'

const props = defineProps<{ posts: CommunityPost[]; searchSource?: SearchSource; error?: string }>()
const emit = defineEmits<{ select: [post: CommunityPost]; write: [] }>()
const stateMessage = computed(() => feedStateMessage(props.posts, props.searchSource ?? 'mysql', props.error))
const photos = ['https://images.unsplash.com/photo-1537996194471-e657df975ab4?auto=format&fit=crop&w=1000&q=80', 'https://images.unsplash.com/photo-1528181304800-259b08848526?auto=format&fit=crop&w=1000&q=80', 'https://images.unsplash.com/photo-1518509562904-e7ef99cdcc86?auto=format&fit=crop&w=1000&q=80']
</script>

<template>
  <main class="feed" aria-label="旅行社区">
    <header class="feed-header"><div><p class="eyebrow">TRAVELERS' NOTES</p><h1>在别人的路上，<br />遇见下一次出发。</h1><p class="intro">真实的走法、意外的风景，还有刚好适合你的目的地。</p></div><button class="write-button" type="button" @click="emit('write')"><PenLine :size="17" />写旅行笔记</button></header>
    <el-alert v-if="stateMessage" class="feed-alert" :title="stateMessage" :type="props.error ? 'error' : 'info'" :closable="false" show-icon />
    <section v-else class="post-list" aria-label="旅行笔记列表">
      <article v-for="(post, index) in posts" :key="post.id" class="post" :style="{ '--reveal-index': index }" tabindex="0" @click="emit('select', post)" @keydown.enter="emit('select', post)">
        <div class="post-image" :style="{ backgroundImage: `url(${photos[index % photos.length]})` }"><span>{{ post.city_code || '旅途见闻' }}</span></div>
        <div class="post-copy"><p class="post-number">NOTE / {{ String(index + 1).padStart(2, '0') }}</p><h2>{{ post.title }}</h2><p class="excerpt">{{ post.body_text }}</p><footer><time>{{ post.published_at ? new Date(post.published_at).toLocaleDateString('zh-CN') : '刚刚发布' }}</time><span><MessageCircle :size="15" />参与讨论</span><span><Bookmark :size="15" />收藏灵感</span><ArrowUpRight :size="19" /></footer></div>
      </article>
    </section>
  </main>
</template>

<style scoped>
.feed { color: var(--field-ink); margin: 0 auto; max-width: 1180px; padding: 62px 28px 90px; }
.feed-header { align-items: end; display: flex; gap: 32px; justify-content: space-between; padding-bottom: 48px; }
.eyebrow, .post-number { color: var(--field-teal); font: 800 11px var(--field-mono); letter-spacing: .1em; margin: 0; }
.feed-header h1 { font-size: clamp(38px, 5vw, 64px); letter-spacing: 0; line-height: 1.13; margin: 14px 0; }
.intro { color: var(--field-ink-soft); line-height: 1.7; margin: 0; }
.write-button { align-items: center; background: var(--field-coral); border: 0; border-radius: 8px; color: #fff; cursor: pointer; display: inline-flex; flex: 0 0 auto; font-weight: 800; gap: 8px; min-height: 46px; padding: 0 17px; transition: background-color var(--motion-base) var(--ease-standard), transform var(--motion-base) var(--ease-standard), box-shadow var(--motion-base) var(--ease-standard); }
.write-button:hover { background: #e6785f; transform: translateY(-2px); box-shadow: 0 10px 22px rgba(216, 110, 88, .3); }
.write-button:active { transform: translateY(0) scale(0.97); }
.write-button:focus-visible { outline: 3px solid var(--field-saffron); outline-offset: 3px; }
.feed-alert { margin-bottom: 24px; }
.post-list { border-top: 1px solid var(--field-line); }
.post { cursor: pointer; display: grid; gap: 30px; grid-template-columns: minmax(210px, .6fr) 1fr; opacity: 0; padding: 25px 0; transform: translateY(12px); transition: opacity var(--motion-slow) var(--ease-out), transform var(--motion-slow) var(--ease-out), background-color var(--motion-fast) var(--ease-standard); transition-delay: calc(var(--reveal-index, 0) * 70ms); }
.post-list .post { opacity: 1; transform: none; }
.post + .post { border-top: 1px solid var(--field-line); }
.post:hover { background: var(--travel-sky); }
.post:active { transform: scale(0.99); }
.post:focus-visible { outline: 3px solid var(--field-saffron); outline-offset: -3px; }
.post-image { aspect-ratio: 1.38; background-position: center; background-size: cover; overflow: hidden; position: relative; transition: transform var(--motion-base) var(--ease-out); }
.post:hover .post-image { transform: scale(1.02); }
.post-image::after { background: linear-gradient(transparent, rgba(8,35,49,.65)); content: ''; inset: 0; position: absolute; }
.post-image span { bottom: 13px; color: #fff; font-size: 12px; font-weight: 800; left: 14px; position: absolute; z-index: 1; }
.post-copy { align-self: center; min-width: 0; }
.post h2 { font-size: clamp(22px, 2.5vw, 31px); line-height: 1.25; margin: 12px 0; transition: color var(--motion-fast) var(--ease-standard); }
.post:hover h2 { color: var(--field-teal); }
.excerpt { -webkit-box-orient: vertical; -webkit-line-clamp: 3; color: var(--field-ink-soft); display: -webkit-box; line-height: 1.7; margin: 0; overflow: hidden; }
.post footer { align-items: center; color: var(--field-muted); display: flex; flex-wrap: wrap; font-size: 12px; gap: 17px; margin-top: 22px; }
.post footer span { align-items: center; display: inline-flex; gap: 5px; transition: color var(--motion-fast) var(--ease-standard); }
.post:hover footer span { color: var(--field-ink-soft); }
.post footer svg:last-child { color: var(--field-coral); margin-left: auto; transition: transform var(--motion-base) var(--ease-out); }
.post:hover footer svg:last-child { transform: translate(3px, -3px); }
@media (max-width: 680px) {
  .feed { padding: 38px 18px 60px; }
  .feed-header { align-items: start; flex-direction: column; padding-bottom: 32px; }
  .write-button { width: 100%; justify-content: center; }
  .post { gap: 17px; grid-template-columns: 1fr; }
  .post-image { aspect-ratio: 1.7; }
  .post h2 { font-size: 24px; }
  .post footer { gap: 12px; }
}
@media (prefers-reduced-motion: reduce) {
  .post, .post-image, .write-button { transition: none; transform: none; opacity: 1; }
}
</style>
