import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import App from './App.vue'

const mocks = vi.hoisted(() => ({ summary: vi.fn(), logout: vi.fn() }))
vi.mock('@/features/notifications/api', () => ({ getUnreadSummary: mocks.summary }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ isConsumerSession: true, user: { nickname: '小林' }, logout: mocks.logout }) }))
vi.mock('vue-router', async (importOriginal) => ({
  ...await importOriginal<typeof import('vue-router')>(),
  useRoute: () => ({ path: '/', meta: {} }),
  useRouter: () => ({ replace: vi.fn() }),
  RouterLink: { props: ['to'], template: '<a :href="typeof to === `string` ? to : to.path"><slot /></a>' },
  RouterView: { template: '<div />' },
}))

describe('global account navigation', () => {
  it('shows message, notification, and personal center controls with unread badges', async () => {
    mocks.summary.mockResolvedValue({ groups: [], total_unread: 4 })
    const wrapper = mount(App, { global: { stubs: { ElContainer: { template: '<div><slot /></div>' }, ElHeader: { template: '<header><slot /></header>' }, ElMain: { template: '<main><slot /></main>' } } } })
    await flushPromises()
    expect(wrapper.find('a[href="/messages"]').text()).not.toContain('4')
    expect(wrapper.find('a[href="/notifications"]').text()).toContain('4')
    expect(wrapper.find('a[href="/me/settings"]').text()).toContain('小林')
    wrapper.unmount()
  })
})
