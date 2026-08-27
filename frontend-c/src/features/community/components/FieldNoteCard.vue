<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import { ArrowUpRight, Copy, MapPin, Route } from 'lucide-vue-next'
import { resolveFieldNoteImage, routeMeta, type FieldNoteSummary } from '../fieldNotesApi'

const props = withDefaults(defineProps<{
  note: FieldNoteSummary
  featured?: boolean
  index?: number
}>(), { featured: false, index: 0 })

const imageUrl = ref('')
const imageFailed = ref(false)
const metadata = computed(() => routeMeta(props.note.itinerary_snapshot))
const destination = computed(() => props.note.city_code || props.note.itinerary_snapshot.title || '路线档案')

function releaseImage() {
  if (imageUrl.value) URL.revokeObjectURL(imageUrl.value)
  imageUrl.value = ''
}

async function loadImage() {
  releaseImage()
  imageFailed.value = false
  if (!props.note.cover_media_id) {
    imageFailed.value = true
    return
  }
  try {
    imageUrl.value = await resolveFieldNoteImage(props.note.cover_media_id)
  } catch {
    imageFailed.value = true
  }
}

watch(() => props.note.cover_media_id, loadImage, { immediate: true })
onUnmounted(releaseImage)
</script>

<template>
  <RouterLink :to="`/community/${note.id}`" class="note-card" :class="{ featured }" :style="{ '--reveal-index': index }">
    <div class="image-frame" :class="{ fallback: imageFailed }">
      <img v-if="imageUrl" :src="imageUrl" :alt="`${note.title} 的路线照片`" />
      <div v-else class="archive-fallback" aria-hidden="true"><Route :size="featured ? 52 : 34" /><span>ROUTE / {{ String(index + 1).padStart(2, '0') }}</span></div>
      <span class="destination"><MapPin :size="13" />{{ destination }}</span>
    </div>
    <div class="card-copy">
      <p class="archive-number">FIELD NOTE / {{ String(index + 1).padStart(2, '0') }}</p>
      <h2>{{ note.title }}</h2>
      <p class="recap">{{ note.recap_text || note.body_text }}</p>
      <footer>
        <span>{{ note.author_id }}</span>
        <span><Route :size="14" />{{ metadata.days }} 日 · {{ metadata.stops }} 站</span>
        <span><Copy :size="14" />{{ note.copy_count }} 次沿用</span>
        <ArrowUpRight class="open-icon" :size="19" aria-hidden="true" />
      </footer>
    </div>
  </RouterLink>
</template>

<style scoped>
.note-card { color: var(--field-ink); display: grid; gap: 22px; grid-template-columns: minmax(190px, .72fr) 1fr; opacity: 0; padding: 24px 0; position: relative; text-decoration: none; transform: translateY(12px); transition: opacity var(--motion-slow) var(--ease-out), transform var(--motion-slow) var(--ease-out), box-shadow var(--motion-base) var(--ease-out); transition-delay: calc(var(--reveal-index, 0) * 70ms); }
.note-card { opacity: 1; transform: none; }
.note-card + .note-card { border-top: 1px solid var(--field-line); }
.note-card.featured { gap: clamp(24px, 4vw, 56px); grid-template-columns: minmax(280px, 1.2fr) 1fr; padding: 0 0 38px; }
.note-card:hover { transform: translateY(-3px); }
.note-card:active { transform: translateY(-1px) scale(0.99); }
.note-card:focus-visible { outline: 3px solid var(--field-saffron); outline-offset: 3px; }
.image-frame { aspect-ratio: 1.42; background: #dce7e3; overflow: hidden; position: relative; transition: transform var(--motion-base) var(--ease-out); }
.note-card:hover .image-frame { transform: scale(1.02); }
.featured .image-frame { aspect-ratio: 1.18; }
.image-frame img { height: 100%; object-fit: cover; transition: transform var(--motion-slow) var(--ease-out); width: 100%; }
.note-card:hover .image-frame img { transform: scale(1.05); }
.archive-fallback { align-items: center; background: #dce7e3; color: var(--field-teal); display: flex; flex-direction: column; gap: 12px; height: 100%; justify-content: center; }
.archive-fallback span { color: var(--field-ink-soft); font: 800 10px var(--field-mono); letter-spacing: .1em; }
.destination { align-items: center; background: rgba(16, 43, 58, .86); bottom: 10px; color: #fff; display: inline-flex; font: 800 11px var(--field-mono); gap: 5px; left: 10px; max-width: calc(100% - 20px); overflow: hidden; padding: 7px 9px; text-overflow: ellipsis; white-space: nowrap; }
.card-copy { align-self: center; min-width: 0; }
.archive-number { color: var(--field-teal); font: 800 10px var(--field-mono); letter-spacing: .11em; margin: 0; }
.card-copy h2 { font-size: clamp(22px, 2.35vw, 32px); line-height: 1.24; margin: 11px 0; transition: color var(--motion-fast) var(--ease-standard); }
.featured .card-copy h2 { font-size: clamp(29px, 3.5vw, 46px); }
.note-card:hover .card-copy h2 { color: var(--field-teal); }
.recap { -webkit-box-orient: vertical; -webkit-line-clamp: 3; color: var(--field-ink-soft); display: -webkit-box; line-height: 1.75; margin: 0; overflow: hidden; }
.card-copy footer { align-items: center; color: var(--field-muted); display: flex; flex-wrap: wrap; font-size: 12px; gap: 13px; margin-top: 21px; }
.card-copy footer span { align-items: center; display: inline-flex; gap: 5px; }
.open-icon { color: var(--field-coral); margin-left: auto; transition: transform var(--motion-base) var(--ease-out); }
.note-card:hover .open-icon { transform: translate(3px, -3px); }
@media (max-width: 640px) {
  .note-card, .note-card.featured { gap: 16px; grid-template-columns: 1fr; padding: 20px 0; }
  .featured .image-frame { aspect-ratio: 1.35; }
  .featured .card-copy h2 { font-size: 30px; }
  .card-copy footer { gap: 10px; }
  .open-icon { display: none; }
}
@media (prefers-reduced-motion: reduce) {
  .note-card, .image-frame, .image-frame img, .open-icon { transition: none; transform: none; opacity: 1; }
}
</style>
