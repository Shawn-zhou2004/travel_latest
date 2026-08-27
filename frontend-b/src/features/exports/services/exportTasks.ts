import { api } from '@/services/api'

export type ExportTaskStatus = 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled'

export interface AdminExportTask {
  id: string
  requester_id: string
  itinerary_id: string
  itinerary_version_id: string
  version_no: number
  format: 'docx'
  status: ExportTaskStatus
  progress: number
  attempt_count: number
  last_attempt_at: string | null
  last_error_code: string | null
  last_error_message: string | null
  created_at: string
  updated_at: string
  finished_at: string | null
}

interface ExportTaskPage {
  items: AdminExportTask[]
  next_cursor: null
}

export async function listAdminExportTasks(status?: ExportTaskStatus) {
  const { data } = await api.get<ExportTaskPage>('/admin/export-tasks', { params: { status, limit: 100 } })
  return data.items
}
