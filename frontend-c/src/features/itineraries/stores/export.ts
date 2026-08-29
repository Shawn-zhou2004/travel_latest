import { computed, ref, shallowRef } from 'vue'
import { defineStore } from 'pinia'
import { createDocxExport, getExportDownloadUrl, getExportTask, retryExportTask, type ExportTask } from '../exportApi'
import { newClientId } from '@/services/id'

export type ExportState = 'idle' | 'submitting' | 'queued' | 'running' | 'succeeded' | 'failed' | 'unavailable'

export const EXPORT_POLL_INTERVAL_MS = 1000
export const EXPORT_MAX_POLL_ATTEMPTS = 30

function errorMessage(reason: unknown) {
  return reason instanceof Error ? reason.message : 'DOCX 导出暂时不可用，请稍后重试。'
}

export const useItineraryExportStore = defineStore('itinerary-export', () => {
  const state = ref<ExportState>('idle')
  const task = shallowRef<ExportTask | null>(null)
  const message = ref('')
  const downloading = ref(false)
  const pollVersion = ref(0)
  let createIdempotencyKey: string | null = null
  const canRetry = computed(() => state.value === 'failed' && task.value?.status === 'failed')

  let pollTimer: ReturnType<typeof setTimeout> | undefined
  let resolvePollWait: (() => void) | undefined

  function stopPolling() {
    pollVersion.value += 1
    if (pollTimer !== undefined) clearTimeout(pollTimer)
    pollTimer = undefined
    resolvePollWait?.()
    resolvePollWait = undefined
  }

  function beginRun() {
    stopPolling()
    return pollVersion.value
  }

  function applyTask(nextTask: ExportTask) {
    task.value = nextTask
    if (nextTask.status === 'queued' || nextTask.status === 'running' || nextTask.status === 'succeeded' || nextTask.status === 'failed') {
      state.value = nextTask.status
    } else {
      state.value = 'unavailable'
      message.value = '导出任务返回了无法识别的状态。'
      return
    }
    message.value = nextTask.status === 'failed'
      ? nextTask.last_error_message || 'DOCX 没有生成成功。'
      : ''
  }

  function waitForNextPoll() {
    return new Promise<void>((resolve) => {
      resolvePollWait = resolve
      pollTimer = setTimeout(() => {
        pollTimer = undefined
        resolvePollWait = undefined
        resolve()
      }, EXPORT_POLL_INTERVAL_MS)
    })
  }

  async function poll(taskId: string, runVersion: number) {
    for (let attempt = 0; attempt < EXPORT_MAX_POLL_ATTEMPTS && runVersion === pollVersion.value; attempt += 1) {
      try {
        const nextTask = await getExportTask(taskId)
        if (runVersion !== pollVersion.value) return
        applyTask(nextTask)
        if (nextTask.status === 'succeeded' || nextTask.status === 'failed') return
        if (attempt < EXPORT_MAX_POLL_ATTEMPTS - 1) await waitForNextPoll()
      } catch (reason) {
        if (runVersion !== pollVersion.value) return
        state.value = 'unavailable'
        message.value = errorMessage(reason)
        return
      }
    }
    if (runVersion === pollVersion.value) {
      state.value = 'unavailable'
      message.value = 'DOCX 导出仍在处理中，请稍后重新打开导出窗口。'
    }
  }

  async function create(itineraryId: string, versionNo: number) {
    if (!itineraryId || versionNo < 1 || state.value === 'submitting' || state.value === 'queued' || state.value === 'running') return
    const runVersion = beginRun()
    task.value = null
    state.value = 'submitting'
    message.value = ''
    try {
      createIdempotencyKey ??= newClientId()
      const createdTask = await createDocxExport(itineraryId, versionNo, createIdempotencyKey)
      if (runVersion !== pollVersion.value) return
      applyTask(createdTask)
      createIdempotencyKey = null
      if (createdTask.status === 'queued' || createdTask.status === 'running') await poll(createdTask.id, runVersion)
    } catch (reason) {
      if (runVersion !== pollVersion.value) return
      state.value = 'unavailable'
      message.value = errorMessage(reason)
    }
  }

  async function retry() {
    if (!canRetry.value || !task.value) return
    const runVersion = beginRun()
    state.value = 'submitting'
    message.value = ''
    try {
      const retriedTask = await retryExportTask(task.value.id)
      if (runVersion !== pollVersion.value) return
      applyTask(retriedTask)
      if (retriedTask.status === 'queued' || retriedTask.status === 'running') await poll(retriedTask.id, runVersion)
    } catch (reason) {
      if (runVersion !== pollVersion.value) return
      state.value = 'unavailable'
      message.value = errorMessage(reason)
    }
  }

  async function download() {
    if (state.value !== 'succeeded' || !task.value || downloading.value) return
    downloading.value = true
    message.value = ''
    try {
      const url = await getExportDownloadUrl(task.value.id)
      const link = document.createElement('a')
      link.href = url
      link.download = ''
      link.rel = 'noopener'
      document.body.append(link)
      link.click()
      link.remove()
    } catch (reason) {
      message.value = errorMessage(reason)
    } finally {
      downloading.value = false
    }
  }

  function reset() {
    stopPolling()
    state.value = 'idle'
    task.value = null
    message.value = ''
    downloading.value = false
    createIdempotencyKey = null
  }

  return { state, task, message, downloading, canRetry, create, retry, download, reset, stopPolling }
})
