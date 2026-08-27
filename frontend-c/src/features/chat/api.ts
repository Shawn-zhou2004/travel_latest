import { api } from '@/services/api'

export interface ChatMessage { id: string; conversation_id: string; sender_id: string; client_message_id: string; message_type: string; body_text: string | null; payload_json: Record<string, unknown> | null; created_at: string; delivery?: 'sending' | 'sent' | 'failed' }
export interface Conversation { id: string; conversation_type: string; title: string | null; avatar_asset_id: string | null; unread_count: number; last_message: ChatMessage | null }

export async function listConversations(cursor?: string) { const { data } = await api.get<{ items: Conversation[]; next_cursor: string | null }>('/conversations', { params: { cursor } }); return data }
export async function listMessages(conversationId: string, cursor?: string) { const { data } = await api.get<{ items: ChatMessage[]; next_cursor: string | null }>(`/conversations/${conversationId}/messages`, { params: { cursor } }); return data }
export async function sendMessage(conversationId: string, clientMessageId: string, bodyText: string) { const { data } = await api.post<ChatMessage>(`/conversations/${conversationId}/messages`, { client_message_id: clientMessageId, message_type: 'text', body_text: bodyText }); return data }
export async function createRealtimeTicket(conversationId: string) { const { data } = await api.post<{ ticket: string }>('/realtime-tickets', { resource_type: 'conversation', resource_id: conversationId }); return data.ticket }

export interface ConversationRealtimeEvent { type: 'message.created'; conversation_id: string; message: ChatMessage }

export function conversationWebSocketUrl(conversationId: string, ticket: string) {
  const url = new URL(`/api/v1/ws/conversations/${conversationId}`, window.location.origin)
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
  url.searchParams.set('ticket', ticket)
  return url.toString()
}

export function mergeChatMessages(current: ChatMessage[], incoming: ChatMessage[]) {
  const byId = new Map(current.map((message) => [message.id, message]))
  for (const message of incoming) {
    const optimistic = current.find((item) => item.client_message_id === message.client_message_id || item.id === message.client_message_id)
    if (optimistic) byId.delete(optimistic.id)
    byId.set(message.id, { ...message, delivery: 'sent' })
  }
  return [...byId.values()].sort((left, right) => left.created_at.localeCompare(right.created_at))
}

export function connectConversationRealtime(
  conversationId: string,
  onEvent: (event: ConversationRealtimeEvent) => void,
  onConnectionChange: (reconnecting: boolean, recovered: boolean) => void = () => undefined,
) {
  let socket: WebSocket | undefined
  let reconnectTimer: ReturnType<typeof setTimeout> | undefined
  let reconnectAttempt = 0
  let stopped = false

  function scheduleReconnect() {
    if (stopped || reconnectTimer) return
    reconnectAttempt += 1
    onConnectionChange(true, false)
    reconnectTimer = setTimeout(() => {
      reconnectTimer = undefined
      void connect()
    }, Math.min(1000 * 2 ** (reconnectAttempt - 1), 30000))
  }

  async function connect() {
    try {
      const ticket = await createRealtimeTicket(conversationId)
      if (stopped) return
      const reconnecting = reconnectAttempt > 0
      socket = new WebSocket(conversationWebSocketUrl(conversationId, ticket))
      socket.onopen = () => {
        if (stopped) return
        reconnectAttempt = 0
        onConnectionChange(false, reconnecting)
      }
      socket.onmessage = (event) => {
        try {
          const payload = JSON.parse(String(event.data)) as ConversationRealtimeEvent | { type?: string }
          if (payload.type === 'ping') socket?.send('pong')
          else if (payload.type === 'message.created') onEvent(payload as ConversationRealtimeEvent)
        } catch {
          // A malformed transport frame must not tear down an otherwise healthy socket.
        }
      }
      socket.onclose = scheduleReconnect
    } catch {
      scheduleReconnect()
    }
  }

  void connect()
  return () => {
    stopped = true
    if (reconnectTimer) clearTimeout(reconnectTimer)
    reconnectTimer = undefined
    if (socket) socket.onclose = null
    socket?.close()
    socket = undefined
  }
}
