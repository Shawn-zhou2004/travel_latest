<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import { ArrowLeft, ArrowDown, ArrowUp, Check, ImagePlus, LoaderCircle, Send, Star, X } from 'lucide-vue-next'
import FieldNoteTimeline from './components/FieldNoteTimeline.vue'
import { canPublish } from './fieldNotesApi'
import { getItinerary, getItineraryVersion, listItineraryVersions, publishFieldNote, type ItineraryDetail, type ItineraryVersion, type ItineraryVersionDetail } from '@/features/itineraries/api'
import { getPrivateImageUrl, uploadPrivateImage } from '@/features/media/api'
import { useReveal } from '@/composables/useReveal'

const props = defineProps<{ itineraryId: string }>()
const router = useRouter()
const itinerary = ref<ItineraryDetail | null>(null)
const versions = ref<ItineraryVersion[]>([])
const selectedVersionNo = ref<number | null>(null)
const selectedVersion = ref<ItineraryVersionDetail | null>(null)
const title = ref('')
const recapText = ref('')
const mediaIds = ref<string[]>([])
const coverMediaId = ref('')
const imageUrls = ref<Record<string, string>>({})
const state = ref<'loading' | 'ready' | 'error'>('loading')
const versionLoading = ref(false)
const uploading = ref(false)
const submitting = ref(false)
const error = ref('')
const validation = ref<Record<string, string>>({})
const root = ref<HTMLElement | null>(null)
useReveal(root)

const canSubmit = computed(() => canPublish({
  versionNo: selectedVersionNo.value,
  title: title.value,
  recap: recapText.value,
  coverId: coverMediaId.value,
  mediaIds: mediaIds.value,
}))

function validate() {
  const errors: Record<string, string> = {}
  if (selectedVersionNo.value === null) errors.version = '请选择一个已保存版本。'
  if (!title.value.trim()) errors.title = '请填写笔记标题。'
  if (!recapText.value.trim()) errors.recap = '请写下这次路线的回顾。'
  if (!mediaIds.value.length) errors.media = '至少上传一张 JPEG、PNG 或 WebP 图片。'
  if (!coverMediaId.value || !mediaIds.value.includes(coverMediaId.value)) errors.cover = '请从已上传图片中选择封面。'
  validation.value = errors
  return !Object.keys(errors).length
}

async function loadVersion(versionNo: number) {
  versionLoading.value = true
  error.value = ''
  selectedVersion.value = null
  try {
    selectedVersion.value = await getItineraryVersion(props.itineraryId, versionNo)
  } catch {
    error.value = '所选版本暂时无法读取，请选择其他版本或重试。'
  } finally {
    versionLoading.value = false
  }
}

async function load() {
  state.value = 'loading'
  try {
    itinerary.value = await getItinerary(props.itineraryId)
    versions.value = await listItineraryVersions(props.itineraryId)
    selectedVersionNo.value = versions.value.find((version) => version.version_no === itinerary.value?.version)?.version_no ?? versions.value[0]?.version_no ?? null
    title.value = itinerary.value.title
    if (selectedVersionNo.value !== null) await loadVersion(selectedVersionNo.value)
    state.value = 'ready'
  } catch {
    state.value = 'error'
    error.value = '发布所需的行程版本无法读取。'
  }
}

watch(selectedVersionNo, (versionNo) => { if (versionNo !== null && state.value === 'ready') void loadVersion(versionNo) })

async function addImages(event: Event) {
  const input = event.target as HTMLInputElement
  const files = Array.from(input.files ?? [])
  input.value = ''
  if (!files.length || uploading.value) return
  uploading.value = true
  error.value = ''
  try {
    for (const file of files) {
      if (mediaIds.value.length >= 9) throw new Error('最多上传 9 张图片。')
      const mediaId = await uploadPrivateImage(file, 'field_note')
      mediaIds.value.push(mediaId)
      imageUrls.value[mediaId] = await getPrivateImageUrl(mediaId)
      if (!coverMediaId.value) coverMediaId.value = mediaId
    }
    validation.value = {}
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '图片上传失败，请重试。'
  } finally {
    uploading.value = false
  }
}

function moveImage(index: number, direction: -1 | 1) {
  const destination = index + direction
  if (destination < 0 || destination >= mediaIds.value.length) return
  const reordered = [...mediaIds.value]
  ;[reordered[index], reordered[destination]] = [reordered[destination], reordered[index]]
  mediaIds.value = reordered
}

function removeImage(mediaId: string) {
  mediaIds.value = mediaIds.value.filter((id) => id !== mediaId)
  if (coverMediaId.value === mediaId) coverMediaId.value = mediaIds.value[0] ?? ''
  URL.revokeObjectURL(imageUrls.value[mediaId])
  delete imageUrls.value[mediaId]
}

async function submit() {
  if (submitting.value || !validate() || selectedVersionNo.value === null) return
  submitting.value = true
  error.value = ''
  try {
    await publishFieldNote(props.itineraryId, {
      version_no: selectedVersionNo.value,
      title: title.value.trim(),
      recap_text: recapText.value.trim(),
      cover_media_id: coverMediaId.value,
      media_ids: mediaIds.value,
    })
    await router.push('/community/mine')
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '投稿没有提交，请检查内容后重试。'
  } finally {
    submitting.value = false
  }
}

onMounted(() => void load())
onBeforeUnmount(() => Object.values(imageUrls.value).forEach((url) => URL.revokeObjectURL(url)))
</script>

<template>
  <main class="publish-page" ref="root">
    <header class="page-header" data-reveal><RouterLink class="back" :to="`/itineraries/${itineraryId}`"><ArrowLeft :size="16" />返回行程</RouterLink><div><p>FIELD NOTE / SUBMISSION</p><h1>发布田野笔记</h1></div></header>
    <section v-if="state === 'loading'" class="state"><LoaderCircle :size="22" class="spin" />正在准备已保存版本。</section>
    <section v-else-if="state === 'error'" class="state error" role="alert"><p>{{ error }}</p><button type="button" @click="load">重新读取</button></section>
    <form v-else class="publish-grid reveal" @submit.prevent="submit">
      <section class="editor-column">
        <label>行程版本<select v-model.number="selectedVersionNo" :aria-invalid="Boolean(validation.version)"><option v-for="version in versions" :key="version.id" :value="version.version_no">版本 {{ version.version_no }} · {{ version.source }}</option></select><Transition name="fade"><small v-if="validation.version">{{ validation.version }}</small></Transition></label>
        <label>笔记标题<input v-model="title" maxlength="200" :aria-invalid="Boolean(validation.title)" placeholder="给这段路线一个名字"><Transition name="fade"><small v-if="validation.title">{{ validation.title }}</small></Transition></label>
        <label>路线回顾<textarea v-model="recapText" rows="7" maxlength="20000" :aria-invalid="Boolean(validation.recap)" placeholder="留下这次出发、停留和回望的理由。"></textarea><Transition name="fade"><small v-if="validation.recap">{{ validation.recap }}</small></Transition></label>
        <section class="media-section" aria-labelledby="photos-heading"><header><div><p>FIELD IMAGES</p><h2 id="photos-heading">图片与封面</h2></div><label class="upload"><ImagePlus :size="16" />{{ uploading ? '上传中' : '上传图片' }}<input type="file" accept="image/jpeg,image/png,image/webp" multiple :disabled="uploading || mediaIds.length >= 9" @change="addImages"></label></header><p>图片会按这里的顺序出现在笔记中。请选择其中一张作为封面。</p><Transition name="fade"><small v-if="validation.media || validation.cover" class="validation">{{ validation.media || validation.cover }}</small></Transition><ol v-if="mediaIds.length" class="media-list"><li v-for="(mediaId, index) in mediaIds" :key="mediaId"><img :src="imageUrls[mediaId]" alt="已上传的田野笔记图片"><div><strong>图片 {{ index + 1 }}</strong><span v-if="coverMediaId === mediaId">当前封面</span></div><div class="media-actions"><button type="button" :aria-label="`将图片 ${index + 1} 上移`" :disabled="index === 0" @click="moveImage(index, -1)"><ArrowUp :size="15" /></button><button type="button" :aria-label="`将图片 ${index + 1} 下移`" :disabled="index === mediaIds.length - 1" @click="moveImage(index, 1)"><ArrowDown :size="15" /></button><button type="button" :class="{ selected: coverMediaId === mediaId }" :aria-label="`设图片 ${index + 1} 为封面`" @click="coverMediaId = mediaId"><Star :size="15" /></button><button type="button" :aria-label="`移除图片 ${index + 1}`" @click="removeImage(mediaId)"><X :size="15" /></button></div></li></ol></section>
        <Transition name="fade"><p v-if="error" class="error-message" role="alert">{{ error }}</p></Transition><button class="submit" type="submit" :disabled="submitting || !canSubmit"><Send :size="16" />{{ submitting ? '正在提交' : '提交审核' }}</button>
      </section>
      <aside class="preview-column"><header><p>IMMUTABLE VERSION</p><h2>路线预览</h2><span v-if="selectedVersionNo !== null">版本 {{ selectedVersionNo }}</span></header><div v-if="versionLoading" class="preview-state"><LoaderCircle :size="18" class="spin" />正在加载该版本。</div><FieldNoteTimeline v-else-if="selectedVersion" :snapshot="selectedVersion.snapshot" /><div v-else class="preview-state">请选择一个可读取版本。</div></aside>
    </form>
  </main>
</template>

<style scoped>
/* ============ 页面容器 ============ */
.publish-page {
  color: var(--field-ink);
  margin: 0 auto;
  max-width: 1220px;
  min-height: calc(100vh - 70px);
  padding: 32px 20px 60px;
}

/* ============ 页头 ============ */
.page-header {
  align-items: end;
  border-bottom: 2px solid var(--field-ink);
  display: flex;
  gap: 28px;
  padding-bottom: 22px;
}

.back {
  align-items: center;
  color: var(--field-teal);
  display: inline-flex;
  font: 800 12px var(--field-mono);
  gap: 6px;
  text-decoration: none;
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

.page-header p,
.media-section header p,
.preview-column header p {
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
.state,
.preview-state {
  align-items: center;
  color: var(--field-muted);
  display: flex;
  gap: 9px;
  justify-content: center;
  min-height: 240px;
}

.state .spin,
.preview-state .spin { color: var(--field-teal); }

.state.error {
  color: var(--field-coral);
  flex-direction: column;
}

.state button {
  background: var(--field-deep);
  border: 0;
  border-radius: var(--travel-radius-sm);
  color: #fff;
  cursor: pointer;
  font-weight: 800;
  padding: 9px 12px;
  transition: background-color var(--motion-base) var(--ease-standard), transform var(--motion-fast) var(--ease-standard), box-shadow var(--motion-base) var(--ease-standard);
}

.state button:hover {
  background: var(--field-teal);
  transform: translateY(-2px);
  box-shadow: 0 6px 16px rgba(8, 126, 120, .24);
}

.state button:active { transform: scale(0.97); }

.state button:focus-visible {
  outline: 3px solid var(--field-saffron);
  outline-offset: 2px;
}

/* ============ 表单布局 ============ */
.publish-grid {
  align-items: start;
  display: grid;
  gap: 48px;
  grid-template-columns: minmax(0, .88fr) minmax(380px, 1.12fr);
  padding-top: 30px;
}

.editor-column {
  display: grid;
  gap: 20px;
}

.editor-column > label {
  color: var(--field-ink-soft);
  display: grid;
  font-size: 12px;
  font-weight: 800;
  gap: 7px;
}

.editor-column input,
.editor-column select,
.editor-column textarea {
  background: #fff;
  border: 1px solid var(--field-line);
  border-radius: var(--travel-radius-sm);
  color: var(--field-ink);
  font: inherit;
  min-height: 42px;
  padding: 10px;
  transition: border-color var(--motion-base) var(--ease-standard), box-shadow var(--motion-base) var(--ease-standard);
}

.editor-column input:focus,
.editor-column select:focus,
.editor-column textarea:focus {
  border-color: var(--field-teal);
  box-shadow: var(--shadow-focus);
  outline: 0;
}

.editor-column textarea {
  line-height: 1.55;
  resize: vertical;
}

.editor-column small,
.validation {
  color: var(--field-coral);
  font-weight: 700;
}

/* ============ 图片区 ============ */
.media-section {
  border-bottom: 1px solid var(--field-line);
  border-top: 1px solid var(--field-line);
  padding: 18px 0;
}

.media-section header {
  align-items: start;
  display: flex;
  justify-content: space-between;
  gap: 18px;
}

.media-section h2,
.preview-column h2 {
  font-size: 21px;
  margin: 0;
}

.media-section > p {
  color: var(--field-muted);
  font-size: 13px;
  line-height: 1.5;
  margin: 10px 0 12px;
}

.upload {
  align-items: center;
  background: var(--field-teal);
  border: 0;
  border-radius: var(--travel-radius-sm);
  color: #fff;
  cursor: pointer;
  display: inline-flex;
  flex: 0 0 auto;
  font-size: 12px;
  font-weight: 800;
  gap: 6px;
  min-height: 38px;
  padding: 0 12px;
  transition: background-color var(--motion-base) var(--ease-standard), transform var(--motion-fast) var(--ease-standard), box-shadow var(--motion-base) var(--ease-standard);
}

.upload:hover {
  background: var(--field-deep);
  transform: translateY(-2px);
  box-shadow: 0 6px 16px rgba(8, 126, 120, .24);
}

.upload:active { transform: scale(0.97); }

.upload:focus-within {
  outline: 3px solid var(--field-saffron);
  outline-offset: 2px;
}

.upload input { display: none; }

/* ============ 图片列表 ============ */
.media-list {
  display: grid;
  gap: 12px;
  grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
  list-style: none;
  margin: 14px 0 0;
  padding: 0;
}

.media-list li {
  background: #fff;
  border: 1px solid var(--field-line);
  border-radius: var(--travel-radius-sm);
  overflow: hidden;
}

.media-list img {
  aspect-ratio: 1.3;
  object-fit: cover;
  width: 100%;
}

.media-list li > div:first-of-type {
  align-items: center;
  display: flex;
  gap: 6px;
  justify-content: space-between;
  padding: 8px 10px;
}

.media-list li strong {
  color: var(--field-ink);
  font-size: 12px;
}

.media-list li span {
  color: var(--field-teal);
  font: 800 10px var(--field-mono);
  letter-spacing: .06em;
}

.media-actions {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 6px;
  padding: 0 10px 10px;
}

.media-actions button {
  align-items: center;
  background: #fff;
  border: 1px solid var(--field-line);
  border-radius: var(--travel-radius-sm);
  color: var(--field-ink-soft);
  cursor: pointer;
  display: inline-flex;
  justify-content: center;
  min-height: 34px;
  transition: border-color var(--motion-base) var(--ease-standard), color var(--motion-base) var(--ease-standard), background-color var(--motion-base) var(--ease-standard), transform var(--motion-fast) var(--ease-standard);
}

.media-actions button:hover:not(:disabled) {
  border-color: var(--field-teal);
  color: var(--field-teal);
  transform: translateY(-1px);
}

.media-actions button:active:not(:disabled) { transform: scale(0.96); }

.media-actions button:focus-visible {
  outline: 3px solid var(--field-saffron);
  outline-offset: 2px;
}

.media-actions button:disabled {
  cursor: not-allowed;
  opacity: 0.4;
}

.media-actions button.selected {
  background: var(--field-teal-soft);
  border-color: var(--field-teal);
  color: var(--field-teal);
}

/* ============ 错误与提交 ============ */
.error-message {
  background: var(--field-white);
  border: 1px solid var(--field-line);
  border-left: 3px solid var(--field-coral);
  border-radius: var(--travel-radius-sm);
  color: var(--field-coral);
  font-size: 13px;
  line-height: 1.55;
  margin: 0;
  padding: 12px 14px;
}

.submit {
  align-items: center;
  background: var(--field-coral);
  border: 0;
  border-radius: var(--travel-radius-sm);
  color: #fff;
  cursor: pointer;
  display: inline-flex;
  font-weight: 800;
  font-size: 15px;
  gap: 8px;
  justify-content: center;
  min-height: 46px;
  padding: 0 20px;
  transition: background-color var(--motion-base) var(--ease-standard), transform var(--motion-fast) var(--ease-standard), box-shadow var(--motion-base) var(--ease-standard);
}

.submit:not(:disabled):hover {
  background: #e6785f;
  transform: translateY(-2px);
  box-shadow: 0 10px 24px rgba(216, 110, 88, .28);
}

.submit:not(:disabled):active { transform: translateY(0) scale(0.97); }

.submit:focus-visible {
  outline: 3px solid var(--field-saffron);
  outline-offset: 3px;
}

.submit:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}

/* ============ 预览列 ============ */
.preview-column {
  background: var(--field-white);
  border: 1px solid var(--field-line);
  border-radius: var(--travel-radius);
  box-shadow: var(--shadow-soft);
  padding: 24px;
}

.preview-column header {
  align-items: center;
  border-bottom: 1px solid var(--field-line);
  display: flex;
  gap: 12px;
  justify-content: space-between;
  margin-bottom: 18px;
  padding-bottom: 14px;
}

.preview-column header span {
  color: var(--field-muted);
  font: 800 11px var(--field-mono);
}

/* ============ 响应式 ============ */
@media (max-width: 880px) {
  .publish-grid {
    grid-template-columns: 1fr;
    gap: 32px;
  }
}

@media (max-width: 600px) {
  .publish-page { padding: 24px 16px 50px; }
  .page-header { flex-direction: column; align-items: start; gap: 14px; }
  .media-section header { flex-direction: column; }
  .upload { align-self: start; }
}

/* ============ 降级 ============ */
@media (prefers-reduced-motion: reduce) {
  .back,
  .state button,
  .upload,
  .media-actions button,
  .submit,
  .editor-column input,
  .editor-column select,
  .editor-column textarea { transition: none; }
  .back:hover,
  .state button:hover,
  .upload:hover,
  .submit:not(:disabled):hover { transform: none; box-shadow: none; }
  .back:active,
  .state button:active,
  .upload:active,
  .media-actions button:active:not(:disabled),
  .submit:not(:disabled):active { transform: none; }
  .media-actions button:hover:not(:disabled) { transform: none; }
}
</style>
