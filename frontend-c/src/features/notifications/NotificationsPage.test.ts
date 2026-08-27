import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import NotificationsPage from './NotificationsPage.vue'

const getUnreadSummary = vi.hoisted(() => vi.fn())
vi.mock('./api', () => ({ getUnreadSummary }))
vi.mock('vue-router', () => ({ RouterLink: { props: ['to'], template: '<a :href="to"><slot /></a>' } }))

describe('NotificationsPage', () => {
  it('renders only aggregated unread group rows', async () => {
    getUnreadSummary.mockResolvedValue({
      total_unread: 2,
      groups: [{
        conversation_id: 'group-1', title: '川西同行', avatar_asset_id: null, unread_count: 2,
        last_message: { id: 'message-1', conversation_id: 'group-1', sender_id: 'user-2', client_message_id: 'client-1', message_type: 'text', body_text: '明早出发', payload_json: null, created_at: '2026-08-13T08:00:00Z' },
      }],
    })
    const wrapper = mount(NotificationsPage)
    await flushPromises()

    expect(wrapper.text()).toContain('川西同行')
    expect(wrapper.text()).toContain('明早出发')
    expect(wrapper.text()).toContain('2 条未读消息')
    expect(wrapper.text()).not.toContain('申请已通过')
    expect(wrapper.find('a[href="/messages/group-1"]').exists()).toBe(true)
  })
})
