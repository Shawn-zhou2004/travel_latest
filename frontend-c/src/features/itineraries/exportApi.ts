import { api } from '@/services/api'

export type ExportTaskStatus = 'queued' | 'running' | 'succeeded' | 'failed'

export interface ExportTask {
  id: string
  itinerary_id: string
  version_no: number
  format: 'docx'
  status: ExportTaskStatus
  progress: number
  output_available: boolean
  attempt_count: number
  last_error_code: string | null
  last_error_message: string | null
  finished_at: string | null
}

export async function createDocxExport(itineraryId: string, versionNo: number, idempotencyKey: string) {
  const { data } = await api.post<ExportTask>('/export-tasks', {
    itinerary_id: itineraryId,
    version_no: versionNo,
    format: 'docx',
  }, { headers: { 'Idempotency-Key': idempotencyKey } })
  return data
}

export async function getExportTask(taskId: string) {
  const { data } = await api.get<ExportTask>(`/export-tasks/${taskId}`)
  return data
}

export async function retryExportTask(taskId: string) {
  const { data } = await api.post<ExportTask>(`/export-tasks/${taskId}/retry`)
  return data
}

export async function getExportDownloadUrl(taskId: string) {
  const { data } = await api.get<{ url: string }>(`/export-tasks/${taskId}/download-url`)
  return data.url
}
