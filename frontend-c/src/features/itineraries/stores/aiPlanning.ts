import { computed, ref, shallowRef } from 'vue'
import { defineStore } from 'pinia'
import { normalizeApiError } from '@/services/api'
import { getMyAIEntitlements, type AIEntitlements } from '@/features/ai/assistantApi'
import {
  createGenerationJob,
  applyGenerationPreview,
  getGenerationPreview,
  getGenerationJob,
  retryGenerationJob,
  type AiPlanningRequest,
  type AiPreview,
  type GenerationJobResponse,
  type GenerationJobStatus,
} from '../aiPlanningApi'

export type AiPlanningState = 'idle' | 'submitting' | 'queued' | 'progress' | 'ready' | 'no_result' | 'clarification' | 'unavailable'

export const AI_POLL_INTERVAL_MS = 1500

const activeStatuses: ReadonlySet<GenerationJobStatus> = new Set([
  'queued',
  'understanding',
  'resolving_destination',
  'retrieving',
  'retrieving_reviewed_sources',
  'searching_live_sources',
  'verifying_pois',
  'planning',
  'validating',
  'awaiting_confirmation',
])

function errorMessage(reason: unknown) {
  const error = normalizeApiError(reason)
  if (error.code === 'TARGET_ITINERARY_EMPTY') return '请先在目标行程中加入至少一个地点，再生成修改预览。'
  if (error.code === 'AI_QUOTA_EXHAUSTED') return '本期 AI 行程生成额度已用完。你填写的内容已保留，可升级会员后继续使用。'
  if (error.code === 'VALIDATION_ERROR') return '请求内容未通过校验：请检查日期跨度（1-7 天）、偏好标签是否重复后重试。'
  return error.message === 'The request could not be completed.' ? 'AI 规划服务暂时不可用，请稍后重试。' : error.message
}

function stateForJob(job: GenerationJobResponse): AiPlanningState {
  if (job.outcome === 'preview') return job.preview_id ? 'ready' : 'unavailable'
  if (job.outcome === 'no_result') return 'no_result'
  if (job.outcome === 'clarification') return 'clarification'
  if (job.outcome === 'unavailable') return 'unavailable'
  if (job.status === 'queued') return 'queued'
  if (activeStatuses.has(job.status)) return 'progress'
  return 'unavailable'
}

function isTerminal(job: GenerationJobResponse) {
  if (job.outcome !== null) return true
  return job.status === 'succeeded' || job.status === 'failed' || job.status === 'cancelled'
}

function snapshotRequest(request: AiPlanningRequest): AiPlanningRequest {
  return {
    ...request,
    preference_tags: request.preference_tags === undefined ? undefined : [...request.preference_tags],
    must_visit_poi_ids: request.must_visit_poi_ids === undefined ? undefined : [...request.must_visit_poi_ids],
  }
}

export const useAiPlanningStore = defineStore('ai-planning', () => {
  const state = ref<AiPlanningState>('idle')
  const job = shallowRef<GenerationJobResponse | null>(null)
  const message = ref('')
  const preview = shallowRef<AiPreview | null>(null)
  const previewLoading = ref(false)
  const applyingPreview = ref(false)
  const appliedItineraryId = ref('')
  const lastRequest = shallowRef<AiPlanningRequest | null>(null)
  const entitlements = shallowRef<AIEntitlements | null>(null)
  const quotaExhausted = ref(false)
  const pollVersion = ref(0)
  const progress = computed(() => Math.max(0, Math.min(100, job.value?.progress ?? 0)))
  const isWorking = computed(() => state.value === 'submitting' || state.value === 'queued' || state.value === 'progress')
  const canRetry = computed(() => !isWorking.value && state.value !== 'idle' && lastRequest.value !== null)

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

  function applyJob(nextJob: GenerationJobResponse) {
    job.value = nextJob
    state.value = stateForJob(nextJob)
    message.value = nextJob.error_code === 'INVALID_DRAFT_SCHEMA'
      ? 'AI 返回的行程格式不完整，未生成可确认的计划。请重试。'
      : nextJob.outcome === 'no_result'
      ? nextJob.error_code === 'CONSTRAINT_VIOLATION'
        ? '行程方案未通过来源或路线校验，未创建预览。请重新生成，或调整偏好后重试。'
        : '未找到足够可验证的地点。请调整偏好后重试，或选择手动规划。'
      : nextJob.message ?? (nextJob.outcome === 'preview' && !nextJob.preview_id
      ? '预览已完成，但后端没有返回 preview_id。'
      : '')
  }

  async function loadPreview() {
    if (!job.value?.preview_id || previewLoading.value) return
    previewLoading.value = true
    try {
      preview.value = await getGenerationPreview(job.value.id)
    } catch (reason) {
      message.value = errorMessage(reason)
    } finally {
      previewLoading.value = false
    }
  }

  function waitForNextPoll() {
    return new Promise<void>((resolve) => {
      resolvePollWait = resolve
      pollTimer = setTimeout(() => {
        pollTimer = undefined
        resolvePollWait = undefined
        resolve()
      }, AI_POLL_INTERVAL_MS)
    })
  }

  async function poll(jobId: string, runVersion: number) {
    while (runVersion === pollVersion.value) {
      try {
        const nextJob = await getGenerationJob(jobId)
        if (runVersion !== pollVersion.value) return
        applyJob(nextJob)
        if (isTerminal(nextJob)) {
          if (nextJob.outcome === 'preview' && nextJob.preview_id) await loadPreview()
          return
        }
        await waitForNextPoll()
      } catch (reason) {
        if (runVersion !== pollVersion.value) return
        state.value = 'unavailable'
        message.value = errorMessage(reason)
        return
      }
    }
  }

  async function restore(jobId: string) {
    const runVersion = beginRun()
    job.value = null
    preview.value = null
    appliedItineraryId.value = ''
    state.value = 'submitting'
    message.value = ''
    try {
      const nextJob = await getGenerationJob(jobId)
      if (runVersion !== pollVersion.value) return false
      applyJob(nextJob)
      if (isTerminal(nextJob)) {
        if (nextJob.outcome === 'preview' && nextJob.preview_id) await loadPreview()
        return true
      }
      await poll(nextJob.id, runVersion)
      return true
    } catch (reason) {
      if (runVersion !== pollVersion.value) return false
      state.value = 'unavailable'
      message.value = errorMessage(reason)
      return false
    }
  }

  async function submit(request: AiPlanningRequest) {
    const runVersion = beginRun()
    lastRequest.value = snapshotRequest(request)
    job.value = null
    preview.value = null
    appliedItineraryId.value = ''
    state.value = 'submitting'
    message.value = ''
    quotaExhausted.value = false

    try {
      const createdJob = await createGenerationJob(lastRequest.value, crypto.randomUUID())
      if (runVersion !== pollVersion.value) return
      applyJob(createdJob)
      await poll(createdJob.id, runVersion)
    } catch (reason) {
      if (runVersion !== pollVersion.value) return
      state.value = 'unavailable'
      message.value = errorMessage(reason)
      quotaExhausted.value = normalizeApiError(reason).code === 'AI_QUOTA_EXHAUSTED'
    }
  }

  async function retry() {
    if (quotaExhausted.value) return
    const currentJob = job.value
    if (currentJob && (currentJob.status === 'failed' || currentJob.status === 'cancelled')) {
      const runVersion = beginRun()
      state.value = 'submitting'
      message.value = ''
      try {
        const retriedJob = await retryGenerationJob(currentJob.id)
        if (runVersion !== pollVersion.value) return
        applyJob(retriedJob)
        await poll(retriedJob.id, runVersion)
      } catch (reason) {
        if (runVersion !== pollVersion.value) return
        state.value = 'unavailable'
        message.value = errorMessage(reason)
      }
      return
    }

    if (lastRequest.value) await submit(lastRequest.value)
  }

  async function loadEntitlements() {
    try { entitlements.value = await getMyAIEntitlements() } catch { /* Balance display is non-blocking. */ }
  }

  async function applyPreview() {
    const currentJob = job.value
    if (!currentJob?.preview_id || !currentJob.target_itinerary_id || applyingPreview.value) return
    applyingPreview.value = true
    try {
      const sourceBaseVersion = lastRequest.value?.base_version ?? preview.value?.base_version
      const version = currentJob.target_itinerary_id && sourceBaseVersion ? sourceBaseVersion : 1
      const result = await applyGenerationPreview(currentJob.id, currentJob.preview_id, version, crypto.randomUUID())
      if (result.code === 'APPLIED') {
        appliedItineraryId.value = currentJob.target_itinerary_id
        message.value = '预览已写入你的行程，路线计算正在排队。'
      } else {
        message.value = result.code === 'VERSION_CONFLICT' ? '行程版本已变化，请刷新后再确认。' : '预览暂时无法写入行程。'
      }
    } catch (reason) {
      message.value = errorMessage(reason)
    } finally {
      applyingPreview.value = false
    }
  }

  function reset() {
    stopPolling()
    state.value = 'idle'
    job.value = null
    message.value = ''
    preview.value = null
    previewLoading.value = false
    applyingPreview.value = false
    appliedItineraryId.value = ''
    lastRequest.value = null
    quotaExhausted.value = false
  }

  return {
    state,
    job,
    message,
    preview,
    previewLoading,
    applyingPreview,
    appliedItineraryId,
    lastRequest,
    entitlements,
    quotaExhausted,
    progress,
    isWorking,
    canRetry,
    submit,
    retry,
    applyPreview,
    restore,
    reset,
    loadEntitlements,
    stopPolling,
  }
})
