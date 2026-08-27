<script setup lang="ts">
import { computed, ref } from 'vue'
import { CheckCircle2, ImagePlus, LoaderCircle, Upload } from 'lucide-vue-next'
import { useReveal } from '@/composables/useReveal'
import { ImageUploadValidationError, uploadPrivateImage, validateImageFile } from '../api'

const root = ref<HTMLElement | null>(null)
useReveal(root)

const emit = defineEmits<{ completed: [assetId: string] }>()

const selectedFile = ref<File | null>(null)
const state = ref<'idle' | 'selected' | 'uploading' | 'completed' | 'error'>('idle')
const message = ref('')

const statusText = computed(() => {
  if (state.value === 'selected' && selectedFile.value) return `已选择：${selectedFile.value.name}`
  if (state.value === 'uploading') return '正在上传到私有存储…'
  if (state.value === 'completed') return '图片已导入，等待你决定如何使用。'
  return message.value
})

function selectFile(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  try {
    validateImageFile(file)
    selectedFile.value = file
    state.value = 'selected'
    message.value = ''
  } catch (error) {
    selectedFile.value = null
    state.value = 'error'
    message.value = error instanceof Error ? error.message : '无法选择这张图片。'
  } finally {
    input.value = ''
  }
}

async function upload() {
  if (!selectedFile.value || state.value === 'uploading') return
  state.value = 'uploading'
  message.value = ''
  try {
    const assetId = await uploadPrivateImage(selectedFile.value, 'itinerary_reference')
    selectedFile.value = null
    state.value = 'completed'
    emit('completed', assetId)
  } catch (error) {
    state.value = 'error'
    message.value = error instanceof Error ? error.message : '图片导入失败，请重试。'
  }
}
</script>

<template>
  <section class="image-import" aria-labelledby="image-import-title" ref="root">
    <div class="image-import-copy">
      <p class="image-import-label">TRIP REFERENCE</p>
      <h3 id="image-import-title">导入一张旅行参考图</h3>
      <p>支持 JPEG、PNG、WebP，最大 10 MiB。图片会私密上传；当前不会识别或解析图片内容。</p>
    </div>
    <div class="image-import-actions" data-reveal>
      <label class="select-image"><ImagePlus :size="16" aria-hidden="true" />选择图片<input type="file" accept="image/jpeg,image/png,image/webp" @change="selectFile"></label>
      <button v-if="state === 'selected' || state === 'error'" class="upload-image" type="button" :disabled="!selectedFile" @click="upload"><Upload :size="16" aria-hidden="true" />上传图片</button>
    </div>
    <Transition name="fade">
      <p v-if="state !== 'idle'" class="image-status" :class="state" :role="state === 'error' ? 'alert' : 'status'" aria-live="polite"><LoaderCircle v-if="state === 'uploading'" class="spin" :size="16" /><CheckCircle2 v-else-if="state === 'completed'" :size="16" />{{ statusText }}</p>
    </Transition>
  </section>
</template>

<style scoped>
.image-import {
  background: linear-gradient(120deg, rgba(30, 99, 87, 0.08), rgba(255, 255, 255, 0) 52%);
  border: 1px solid var(--field-line);
  border-radius: var(--travel-radius-sm);
  display: grid;
  gap: 18px;
  margin-top: 12px;
  padding: 20px;
  position: relative;
  overflow: hidden;
}

.image-import::after {
  border: 1px solid rgba(42, 129, 129, 0.15);
  border-radius: 50%;
  content: '';
  height: 112px;
  pointer-events: none;
  position: absolute;
  right: -42px;
  top: -54px;
  width: 112px;
}

.image-import-copy { position: relative; z-index: 1; }

.image-import-label {
  color: var(--field-teal);
  font: 800 10px var(--field-mono);
  letter-spacing: 0.12em;
  margin: 0 0 8px;
  text-transform: uppercase;
}

.image-import h3 {
  color: var(--field-ink);
  font-size: 18px;
  line-height: 1.3;
  margin: 0;
}

.image-import p:not(.image-import-label, .image-status) {
  color: var(--field-muted);
  font-size: 12px;
  line-height: 1.65;
  margin: 7px 0 0;
  max-width: 52ch;
}

.image-import-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 9px;
  position: relative;
  z-index: 1;
}

.select-image,
.upload-image {
  align-items: center;
  border: 1px solid var(--field-line);
  border-radius: var(--travel-radius-sm);
  cursor: pointer;
  display: inline-flex;
  font-size: 12px;
  font-weight: 800;
  gap: 7px;
  min-height: 40px;
  padding: 8px 13px;
  transition: background-color var(--motion-fast) var(--ease-standard),
    border-color var(--motion-fast) var(--ease-standard),
    color var(--motion-fast) var(--ease-standard),
    transform var(--motion-fast) var(--ease-standard),
    box-shadow var(--motion-fast) var(--ease-standard);
}

.select-image {
  background: var(--field-white);
  color: var(--field-ink);
}

.select-image:hover {
  background: var(--field-teal-soft);
  border-color: var(--field-teal);
  color: var(--field-teal);
  transform: translateY(-1px);
}

.select-image:active { transform: translateY(0) scale(0.98); }

.select-image input {
  height: 1px;
  opacity: 0;
  overflow: hidden;
  position: absolute;
  width: 1px;
}

.upload-image {
  background: var(--field-deep);
  border-color: var(--field-deep);
  color: var(--field-white);
}

.upload-image:not(:disabled):hover {
  background: var(--field-teal);
  border-color: var(--field-teal);
  transform: translateY(-1px);
  box-shadow: 0 6px 16px rgba(8, 126, 120, 0.22);
}

.upload-image:not(:disabled):active { transform: translateY(0) scale(0.97); }

.upload-image:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}

/* ============ 状态提示 ============ */
.image-status {
  align-items: center;
  border-top: 1px solid var(--field-line);
  color: var(--field-muted);
  display: flex;
  font-size: 12px;
  gap: 7px;
  line-height: 1.45;
  margin: 0;
  padding-top: 14px;
  position: relative;
  z-index: 1;
}

.image-status svg { flex-shrink: 0; }

.image-status.selected { color: var(--field-ink-soft); }

.image-status.uploading {
  color: var(--field-teal);
}

.image-status.uploading svg { color: var(--field-teal); }

.image-status.completed {
  color: var(--field-teal);
  font-weight: 700;
}

.image-status.completed svg { color: var(--field-teal); }

.image-status.error {
  background: rgba(216, 110, 88, 0.08);
  border-left: 3px solid var(--field-coral);
  border-radius: var(--travel-radius-sm);
  color: #9c4234;
  font-weight: 700;
  padding: 10px 12px;
}

/* ============ 焦点光晕 ============ */
.select-image:focus-within,
.upload-image:focus-visible {
  outline: none;
  border-color: var(--field-saffron);
  box-shadow: var(--shadow-focus);
}

/* ============ 入场工具 ============ */
.spin { animation: spin 0.9s linear infinite; }

@keyframes spin { to { transform: rotate(360deg); } }

@media (prefers-reduced-motion: reduce) {
  .spin { animation: none; }
  .select-image,
  .upload-image { transition: none; }
}
</style>
