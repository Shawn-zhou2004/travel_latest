import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const service = vi.hoisted(() => ({ listAdminUsers: vi.fn(), updateAdminUser: vi.fn() }))
vi.mock('../services/users', () => service)
vi.mock('@/services/api', () => ({ normalizeApiError: (cause: unknown) => ({ message: String(cause) }) }))

import UsersPage from './UsersPage.vue'

const user = {
  id: 'user-1', phone_masked: '138****5678', nickname: 'Alice', status: 'active' as const,
  roles: ['user', 'provider_staff'], provider_memberships: ['provider-1'],
  created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-02T00:00:00Z',
}

function mountPage() { return mount(UsersPage) }

beforeEach(() => { vi.clearAllMocks(); service.listAdminUsers.mockResolvedValue({ items: [user], next_cursor: null }) })

describe('UsersPage', () => {
  it('renders masked account details and read-only fields', async () => {
    const wrapper = mountPage()
    await flushPromises()
    expect(wrapper.text()).toContain('Alice')
    expect(wrapper.text()).toContain('138****5678')
    expect(wrapper.text()).toContain('供应商员工')
    expect(wrapper.text()).toContain('活跃')
    expect(wrapper.text()).not.toContain('13812345678')
  })

  it('renders a retryable error', async () => {
    service.listAdminUsers.mockRejectedValue(new Error('Directory unavailable'))
    const wrapper = mountPage()
    await flushPromises()
    expect(wrapper.text()).toContain('Directory unavailable')
    expect(wrapper.text()).toContain('重新尝试')
  })

  it('renders the empty state', async () => {
    service.listAdminUsers.mockResolvedValue({ items: [], next_cursor: null })
    const wrapper = mountPage()
    await flushPromises()
    expect(wrapper.text()).toContain('暂无用户')
  })

  it('suspends an active user without editing their scoped roles', async () => {
    service.updateAdminUser.mockResolvedValue({ ...user, status: 'suspended' })
    const wrapper = mountPage()
    await flushPromises()
    await wrapper.get('button').trigger('click')
    await flushPromises()
    const suspendButton = wrapper.findAll('button').find((button) => button.text() === '暂停')
    await suspendButton!.trigger('click')
    await flushPromises()
    expect(service.updateAdminUser).toHaveBeenCalledWith('user-1', { status: 'suspended' })
    expect(wrapper.text()).toContain('已暂停')
    expect(wrapper.text()).toContain('供应商员工')
  })
})
