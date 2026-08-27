import { beforeEach, describe, expect, it, vi } from 'vitest'
import { getUnreadSummary, listNotifications, markNotificationsRead, notificationDestination } from './api'

const { api } = vi.hoisted(() => ({ api: { get: vi.fn(), post: vi.fn() } }))

vi.mock('@/services/api', () => ({ api }))

describe('notification API', () => {
  beforeEach(() => vi.clearAllMocks())

  it('uses the documented notification endpoints', async () => {
    api.get.mockResolvedValue({ data: { items: [] } })
    api.post.mockResolvedValue({ data: { updated_count: 1 } })

    await listNotifications()
    api.get.mockResolvedValueOnce({ data: { groups: [], total_unread: 3 } })
    expect(await getUnreadSummary()).toEqual({ groups: [], total_unread: 3 })
    await markNotificationsRead(['notification-1'])
    await markNotificationsRead()

    expect(api.get).toHaveBeenCalledWith('/notifications')
    expect(api.get).toHaveBeenCalledWith('/notifications/summary')
    expect(api.post).toHaveBeenNthCalledWith(1, '/notifications:mark-read', { notification_ids: ['notification-1'] })
    expect(api.post).toHaveBeenNthCalledWith(2, '/notifications:mark-read', {})
  })

  it('links new companion applications to the owner plan detail', () => {
    expect(notificationDestination({ notification_type: 'companion_application.created', payload: { request_id: 'plan-1' } })).toBe('/companions/plan-1')
    expect(notificationDestination({ notification_type: 'message.created', payload: { request_id: 'plan-1' } })).toBeNull()
    expect(notificationDestination({ notification_type: 'message.created', payload: { conversation_id: 'chat-1' } })).toBe('/messages/chat-1')
    expect(notificationDestination({ notification_type: 'companion_application.accepted', payload: { conversation_id: 'chat-2' } })).toBe('/messages/chat-2')
    expect(notificationDestination({ notification_type: 'companion_application.created', payload: {} })).toBeNull()
  })
})
