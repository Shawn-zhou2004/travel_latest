import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createAiMemory, getMyAIEntitlements, syncSettingsToAiMemory } from './assistantApi'

const { api } = vi.hoisted(() => ({ api: { get: vi.fn(), post: vi.fn() } }))
vi.mock('@/services/api', () => ({ api, clearSession: vi.fn(), getAccessToken: vi.fn(), refreshAccessToken: vi.fn() }))
vi.mock('@/services/session', () => ({ clearSession: vi.fn(), getAccessToken: vi.fn() }))

describe('assistant API', () => {
  beforeEach(() => vi.clearAllMocks())
  it('loads the current free and membership AI balances', async () => {
    api.get.mockResolvedValue({ data: { free: {}, membership: null } })
    await getMyAIEntitlements()
    expect(api.get).toHaveBeenCalledWith('/users/me/ai-entitlements')
  })

  it('creates an explicit profile memory from plain text', async () => {
    api.post.mockResolvedValue({ data: { id: 'memory-1' } })

    await createAiMemory('profile', '饮食偏好', '不吃辣')

    expect(api.post).toHaveBeenCalledWith('/ai/memories', {
      memory_type: 'profile',
      memory_key: '饮食偏好',
      memory_value: { text: '不吃辣' },
      source: 'user',
      confidence: 1,
    })
  })

  it('syncs the current settings to the server-owned travel profile', async () => {
    api.post.mockResolvedValue({ data: { id: 'travel-profile' } })

    await syncSettingsToAiMemory()

    expect(api.post).toHaveBeenCalledWith('/users/me/settings:sync-ai-memory')
  })
})
