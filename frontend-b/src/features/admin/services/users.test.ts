import { describe, expect, it, vi } from 'vitest'

const get = vi.hoisted(() => vi.fn())
const patch = vi.hoisted(() => vi.fn())
vi.mock('@/services/api', () => ({ api: { get, patch } }))
import { listAdminUsers, updateAdminUser } from './users'

describe('admin user service', () => {
  it('requests the typed directory page', async () => {
    const data = { items: [], next_cursor: null }
    get.mockResolvedValue({ data })
    await expect(listAdminUsers({ query: '138', limit: 20, cursor: 'next' })).resolves.toEqual(data)
    expect(get).toHaveBeenCalledWith('/admin/users', { params: { query: '138', limit: 20, cursor: 'next' } })
  })

  it('updates only a user status', async () => {
    const data = { id: 'user-1', status: 'suspended' }
    patch.mockResolvedValue({ data })
    await expect(updateAdminUser('user-1', { status: 'suspended' })).resolves.toEqual(data)
    expect(patch).toHaveBeenCalledWith('/admin/users/user-1', { status: 'suspended' })
  })
})
