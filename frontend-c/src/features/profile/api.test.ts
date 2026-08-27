import { describe, expect, it, vi } from 'vitest'
import { getMyProfile, updateMyProfile } from './api'

const { api } = vi.hoisted(() => ({ api: { get: vi.fn(), patch: vi.fn() } }))
vi.mock('@/services/api', () => ({ api }))

describe('profile API', () => {
  it('uses auth/me for reads and users/me for updates', async () => {
    api.get.mockResolvedValueOnce({ data: { id: 'u1', phone: '13800000000', nickname: null, avatar_asset_id: null } })
    api.patch.mockResolvedValueOnce({ data: { id: 'u1', phone: '13800000000', nickname: 'Kai', avatar_asset_id: null } })
    await expect(getMyProfile()).resolves.toMatchObject({ id: 'u1' })
    await expect(updateMyProfile({ nickname: 'Kai' })).resolves.toMatchObject({ nickname: 'Kai' })
    expect(api.get).toHaveBeenCalledWith('/auth/me')
    expect(api.patch).toHaveBeenCalledWith('/users/me', { nickname: 'Kai' })
  })
})
