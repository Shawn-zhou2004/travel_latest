import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { api } from '@/services/api'
import { connectConversationRealtime, conversationWebSocketUrl, listConversations, mergeChatMessages, type ChatMessage } from './api'
import ChatPage from './ChatPage.vue'

vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ user: { id: 'user-1' } }) }))

class FakeWebSocket {
  static instances: FakeWebSocket[] = []
  onopen: (() => void) | null = null
  onmessage: ((event: { data: string }) => void) | null = null
  onclose: (() => void) | null = null
  sent: string[] = []
  closed = false

  constructor(public url: string) { FakeWebSocket.instances.push(this) }
  send(value: string) { this.sent.push(value) }
  close() { this.closed = true; this.onclose?.() }
  open() { this.onopen?.() }
  message(payload: object) { this.onmessage?.({ data: JSON.stringify(payload) }) }
  disconnect() { this.onclose?.() }
}

afterEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()
  FakeWebSocket.instances = []
})

describe('chat realtime contracts', () => {
  it('builds a secure websocket URL with only the one-time ticket', () => {
    const url = new URL(conversationWebSocketUrl('conversation-1', 'ticket-1'))
    expect(url.pathname).toBe('/api/v1/ws/conversations/conversation-1')
    expect(url.searchParams.get('ticket')).toBe('ticket-1')
    expect(url.searchParams.has('access_token')).toBe(false)
    expect(url.searchParams.has('user_id')).toBe(false)
  })

  it('deduplicates realtime and history messages and replaces optimistic sends', () => {
    const optimistic: ChatMessage = { id: 'client-1', conversation_id: 'c1', sender_id: 'u1', client_message_id: 'client-1', message_type: 'text', body_text: 'hello', payload_json: null, created_at: '2026-08-01T00:00:00Z', delivery: 'sending' }
    const persisted: ChatMessage = { ...optimistic, id: 'message-1', delivery: undefined }
    const merged = mergeChatMessages([optimistic], [persisted, persisted])
    expect(merged).toEqual([{ ...persisted, delivery: 'sent' }])
  })

  it('preserves persisted group title and avatar metadata in the conversation list', async () => {
    vi.spyOn(api, 'get').mockResolvedValue({ data: { items: [{ id: 'conversation-1', conversation_type: 'companion_group', title: '西湖慢行小组', avatar_asset_id: 'asset-1', unread_count: 2, last_message: null }], next_cursor: null } } as never)
    const response = await listConversations()
    expect(response.items[0]).toMatchObject({ title: '西湖慢行小组', avatar_asset_id: 'asset-1' })
  })

  it('renders the persisted group title and private avatar in the chat list', async () => {
    vi.stubGlobal('WebSocket', FakeWebSocket)
    vi.spyOn(api, 'get').mockImplementation(async (url) => {
      if (url === '/conversations') return { data: { items: [{ id: 'conversation-1', conversation_type: 'companion_group', title: '西湖慢行小组', avatar_asset_id: 'asset-1', unread_count: 0, last_message: null }], next_cursor: null } } as never
      if (url === '/media/asset-1/download-url') return { data: { url: 'https://storage.example/group-avatar' } } as never
      return { data: { items: [], next_cursor: null } } as never
    })
    vi.spyOn(api, 'post').mockResolvedValue({ data: { ticket: 'ticket-1' } } as never)
    const wrapper = mount(ChatPage, { props: { conversationId: 'conversation-1' }, global: { stubs: { RouterLink: { props: ['to'], template: '<a><slot /></a>' }, ChatHistory: true, ChatComposer: true } } })
    await flushPromises()
    expect(wrapper.text()).toContain('西湖慢行小组')
    expect(wrapper.find('img[alt="西湖慢行小组头像"]').attributes('src')).toBe('https://storage.example/group-avatar')
    wrapper.unmount()
  })

  it('delivers immediately, answers heartbeat, reconnects with a fresh ticket, and cleans up', async () => {
    vi.useFakeTimers()
    vi.stubGlobal('WebSocket', FakeWebSocket)
    const post = vi.spyOn(api, 'post')
      .mockResolvedValueOnce({ data: { ticket: 'ticket-1' } })
      .mockResolvedValueOnce({ data: { ticket: 'ticket-2' } })
    const received = vi.fn()
    const connectionChange = vi.fn()

    const cleanup = connectConversationRealtime('conversation-1', received, connectionChange)
    await vi.waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1))
    const first = FakeWebSocket.instances[0]
    first.open()
    first.message({ type: 'ping' })
    first.message({ type: 'message.created', conversation_id: 'conversation-1', message: { id: 'message-1' } })
    expect(first.sent).toEqual(['pong'])
    expect(received).toHaveBeenCalledOnce()

    first.disconnect()
    await vi.advanceTimersByTimeAsync(1000)
    await vi.waitFor(() => expect(FakeWebSocket.instances).toHaveLength(2))
    const second = FakeWebSocket.instances[1]
    second.open()
    expect(post).toHaveBeenCalledTimes(2)
    expect(new URL(second.url).searchParams.get('ticket')).toBe('ticket-2')
    expect(connectionChange).toHaveBeenLastCalledWith(false, true)

    cleanup()
    expect(second.closed).toBe(true)
    await vi.advanceTimersByTimeAsync(30000)
    expect(FakeWebSocket.instances).toHaveLength(2)
  })
})
