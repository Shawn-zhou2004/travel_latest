import { api } from '@/services/api'
import type { ChatMessage } from '@/features/chat/api'

export interface GroupUnreadSummary {
  conversation_id: string
  title: string
  avatar_asset_id: string | null
  unread_count: number
  last_message: ChatMessage | null
}

export interface Notification {
  id: string
  notification_type: string
  payload: Record<string, unknown>
  created_at: string
  read_at: string | null
}

export function notificationDestination(notification: Pick<Notification, 'notification_type' | 'payload'>) {
  const requestId = notification.payload.request_id
  const conversationId = notification.payload.conversation_id
  if (['companion_application.accepted', 'message.created'].includes(notification.notification_type) && typeof conversationId === 'string') return `/messages/${conversationId}`
  return notification.notification_type === 'companion_application.created' && typeof requestId === 'string' ? `/companions/${requestId}` : null
}

interface NotificationListResponse {
  items: Notification[]
  next_cursor?: string | null
}

export async function listNotifications() {
  const { data } = await api.get<NotificationListResponse>('/notifications')
  return data
}

export async function markNotificationsRead(notificationIds?: string[]) {
  await api.post('/notifications:mark-read', notificationIds?.length ? { notification_ids: notificationIds } : {})
}

export async function getUnreadSummary() {
  const { data } = await api.get<{ groups: GroupUnreadSummary[]; total_unread: number }>('/notifications/summary')
  return data
}
