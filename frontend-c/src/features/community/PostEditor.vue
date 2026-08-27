<script setup lang="ts">
import { ArrowLeft, Send } from 'lucide-vue-next'
import { ref } from 'vue'
import { useReveal } from '@/composables/useReveal'

const emit = defineEmits<{ submit: [value: { title: string; body_text: string; city_code: string }]; cancel: [] }>()
const title = ref('')
const bodyText = ref('')
const cityCode = ref('')
const submitting = ref(false)
const root = ref<HTMLElement | null>(null)
useReveal(root)
async function submit() { if (!title.value.trim()) return; submitting.value = true; emit('submit', { title: title.value.trim(), body_text: bodyText.value.trim(), city_code: cityCode.value.trim() }); submitting.value = false }
</script>

<template>
  <main class="editor-page" ref="root">
    <form class="editor" @submit.prevent="submit">
      <header data-reveal>
        <button class="back-button" type="button" @click="emit('cancel')"><ArrowLeft :size="17" />返回笔记</button>
        <p class="eyebrow">NEW TRAVEL NOTE</p>
        <h1>写下路上的这一刻。</h1>
        <p>不必写得完美。一个地点、一段感受，都会成为别人出发时的参考。</p>
      </header>
      <div class="editor-fields" data-reveal>
        <el-form-item label="这篇笔记想叫"><el-input v-model="title" maxlength="200" show-word-limit placeholder="例如：在泉州的第三天，我没有赶路" /></el-form-item>
        <el-form-item label="发生在哪座城市"><el-input v-model="cityCode" maxlength="32" placeholder="例如：泉州" /></el-form-item>
        <el-form-item label="把这段路讲给后来的人"><el-input v-model="bodyText" type="textarea" :rows="11" maxlength="20000" show-word-limit placeholder="说说你看见的风景、走过的路，或想提醒旅人的小事。" /></el-form-item>
      </div>
      <footer class="actions" data-reveal>
        <span>发布后会出现在旅行社区</span>
        <button class="publish-button" type="submit" :disabled="!title.trim() || submitting"><Send :size="16" />{{ submitting ? '正在发布' : '发布笔记' }}</button>
      </footer>
    </form>
  </main>
</template>

<style scoped>
/* ============ 页面容器 ============ */
.editor-page {
  background: linear-gradient(105deg, #ddece9 0%, var(--field-paper) 48%);
  min-height: calc(100vh - 70px);
  padding: 52px 24px 80px;
}

.editor {
  margin: 0 auto;
  max-width: 820px;
}

/* ============ 返回按钮 ============ */
.back-button {
  align-items: center;
  background: transparent;
  border: 0;
  color: var(--field-teal);
  cursor: pointer;
  display: inline-flex;
  font-size: 13px;
  font-weight: 800;
  gap: 7px;
  padding: 0;
  transition: color var(--motion-fast) var(--ease-standard), transform var(--motion-fast) var(--ease-standard);
}

.back-button:hover {
  color: var(--field-deep);
  transform: translateX(-3px);
}

.back-button:active { transform: scale(0.97); }

.back-button:focus-visible {
  outline: 3px solid var(--field-saffron);
  outline-offset: 3px;
  border-radius: var(--travel-radius-sm);
}

/* ============ 页头 ============ */
.eyebrow {
  color: var(--field-coral);
  font: 800 11px var(--field-mono);
  letter-spacing: .1em;
  margin: 46px 0 12px;
}

.editor header h1 {
  font-size: clamp(34px, 4vw, 52px);
  line-height: 1.15;
  margin: 0;
}

.editor header > p:last-child {
  color: var(--field-ink-soft);
  line-height: 1.7;
  margin: 14px 0 0;
  max-width: 460px;
}

/* ============ 表单字段卡 ============ */
.editor-fields {
  background: #fff;
  border-top: 3px solid var(--field-teal);
  border-radius: var(--travel-radius-sm);
  box-shadow: var(--shadow-lift);
  margin-top: 42px;
  padding: 28px;
}

.editor-fields :deep(.el-form-item) { margin-bottom: 26px; }
.editor-fields :deep(.el-form-item:last-child) { margin-bottom: 0; }
.editor-fields :deep(.el-form-item__label) {
  color: var(--field-ink);
  font-weight: 800;
}
.editor-fields :deep(.el-input__wrapper),
.editor-fields :deep(.el-textarea__inner) {
  box-shadow: 0 0 0 1px var(--field-line) inset;
}
.editor-fields :deep(.el-input__wrapper.is-focus),
.editor-fields :deep(.el-textarea__inner:focus) {
  box-shadow: 0 0 0 1px var(--field-teal) inset;
}

/* ============ 操作区 ============ */
.actions {
  align-items: center;
  display: flex;
  justify-content: space-between;
  margin-top: 18px;
}

.actions span {
  color: var(--field-muted);
  font-size: 12px;
}

.publish-button {
  align-items: center;
  background: var(--field-coral);
  border: 0;
  border-radius: var(--travel-radius-sm);
  color: #fff;
  cursor: pointer;
  display: inline-flex;
  font-weight: 800;
  gap: 8px;
  min-height: 44px;
  padding: 0 17px;
  transition: background-color var(--motion-base) var(--ease-standard), transform var(--motion-fast) var(--ease-standard), box-shadow var(--motion-base) var(--ease-standard);
}

.publish-button:not(:disabled):hover {
  background: #e6785f;
  transform: translateY(-2px);
  box-shadow: 0 10px 24px rgba(216, 110, 88, .28);
}

.publish-button:not(:disabled):active { transform: translateY(0) scale(0.97); }

.publish-button:focus-visible {
  outline: 3px solid var(--field-saffron);
  outline-offset: 3px;
}

.publish-button:disabled {
  cursor: wait;
  opacity: 0.58;
}

/* ============ 响应式 ============ */
@media (max-width: 600px) {
  .editor-page { padding: 30px 16px 55px; }
  .eyebrow { margin-top: 34px; }
  .editor-fields {
    margin-top: 30px;
    padding: 19px 16px;
  }
  .actions {
    align-items: stretch;
    flex-direction: column-reverse;
    gap: 14px;
  }
  .publish-button { justify-content: center; }
  .actions span { text-align: center; }
}

/* ============ 降级 ============ */
@media (prefers-reduced-motion: reduce) {
  .back-button,
  .publish-button { transition: none; }
  .back-button:hover { transform: none; }
  .back-button:active { transform: none; }
  .publish-button:not(:disabled):hover { transform: none; box-shadow: none; }
  .publish-button:not(:disabled):active { transform: none; }
}
</style>
