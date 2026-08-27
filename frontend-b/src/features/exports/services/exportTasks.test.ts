import { describe, expect, it, vi } from 'vitest'

const { get } = vi.hoisted(() => ({ get: vi.fn() }))
vi.mock('@/services/api', () => ({ api: { get } }))

import { listAdminExportTasks } from './exportTasks'

describe('listAdminExportTasks', () => {
  it('requests the bounded admin metadata collection with a status filter', async () => {
    get.mockResolvedValueOnce({ data: { items: [], next_cursor: null } })

    await expect(listAdminExportTasks('failed')).resolves.toEqual([])

    expect(get).toHaveBeenCalledWith('/admin/export-tasks', { params: { status: 'failed', limit: 100 } })
  })
})
