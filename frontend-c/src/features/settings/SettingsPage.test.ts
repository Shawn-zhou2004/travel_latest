import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import SettingsPage from './SettingsPage.vue'

const { getMyProfile, updateMyProfile, getMySettings, updateMySettings, getPrivateImageUrl, uploadPrivateImage, syncSettingsToAiMemory } = vi.hoisted(() => ({
  getMyProfile: vi.fn(), updateMyProfile: vi.fn(), getMySettings: vi.fn(), updateMySettings: vi.fn(), getPrivateImageUrl: vi.fn(), uploadPrivateImage: vi.fn(), syncSettingsToAiMemory: vi.fn(),
}))
vi.mock('@/features/profile/api', () => ({ getMyProfile, updateMyProfile }))
vi.mock('./api', () => ({ getMySettings, updateMySettings, interestTags: [{ value: '吃吃喝喝', label: '吃吃喝喝' }] }))
vi.mock('@/features/media/api', () => ({ getPrivateImageUrl, uploadPrivateImage }))
vi.mock('@/features/ai/assistantApi', () => ({ syncSettingsToAiMemory }))

const profile = { id: 'u1', phone: '13800000000', nickname: '小林', avatar_asset_id: null }
const settings = { departure_city: '杭州', budget_level: 'balanced', travel_pace: 'balanced', interest_tags: ['吃吃喝喝'], traveler_type: 'friends', notifications_enabled: true, order_notifications: true, itinerary_notifications: true, community_notifications: true, profile_visibility: 'collaborators' } as const

async function mountLoaded() {
  const pinia = createPinia()
  setActivePinia(pinia)
  const wrapper = mount(SettingsPage, { global: { plugins: [pinia] } })
  await flushPromises()
  return wrapper
}

describe('SettingsPage', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    getMyProfile.mockResolvedValue(profile)
    getMySettings.mockResolvedValue(settings)
    updateMyProfile.mockResolvedValue(profile)
    updateMySettings.mockResolvedValue(settings)
    getPrivateImageUrl.mockResolvedValue('')
    syncSettingsToAiMemory.mockResolvedValue({ id: 'travel-profile' })
  })

  it('loads profile and settings into separate editable sections', async () => {
    const wrapper = await mountLoaded()
    expect(wrapper.get('[data-testid="settings-profile"]').text()).toContain('账户资料')
    expect(wrapper.get('[data-testid="settings-travel"]').text()).toContain('旅行偏好')
    expect((wrapper.get('input[name="departure-city"]').element as HTMLInputElement).value).toBe('杭州')
  })

  it('keeps local edits and exposes an API error after a section save fails', async () => {
    updateMySettings.mockRejectedValue(new Error('保存失败'))
    const wrapper = await mountLoaded()
    await wrapper.get('input[name="departure-city"]').setValue('上海')
    await wrapper.get('[data-testid="save-travel"]').trigger('click')
    await flushPromises()
    expect((wrapper.get('input[name="departure-city"]').element as HTMLInputElement).value).toBe('上海')
    expect(wrapper.text()).toContain('保存失败')
  })

  it('saves only the edited travel section as a partial settings update', async () => {
    const wrapper = await mountLoaded()
    await wrapper.get('input[name="departure-city"]').setValue('上海')
    await wrapper.get('[data-testid="save-travel"]').trigger('click')
    await flushPromises()
    expect(updateMySettings).toHaveBeenCalledWith({
      departure_city: '上海',
      budget_level: 'balanced',
      travel_pace: 'balanced',
      interest_tags: ['吃吃喝喝'],
      traveler_type: 'friends',
    })
    expect(wrapper.text()).toContain('旅行偏好已保存。')
    expect(syncSettingsToAiMemory).not.toHaveBeenCalled()
  })

  it('syncs travel settings only after an explicit click', async () => {
    const wrapper = await mountLoaded()

    expect(syncSettingsToAiMemory).not.toHaveBeenCalled()
    await wrapper.get('[data-testid="sync-ai-memory"]').trigger('click')
    await flushPromises()

    expect(syncSettingsToAiMemory).toHaveBeenCalledOnce()
    expect(wrapper.text()).toContain('当前设置已更新到 AI 旅行档案。')
  })

  it('requires saving changed travel preferences before syncing AI memory', async () => {
    const wrapper = await mountLoaded()
    await wrapper.get('input[name="departure-city"]').setValue('上海')
    const syncButton = wrapper.get('[data-testid="sync-ai-memory"]')

    expect(wrapper.text()).toContain('请先保存旅行偏好，再同步为 AI 记忆。')
    expect(syncButton.attributes('disabled')).toBeDefined()
    await syncButton.trigger('click')
    expect(syncSettingsToAiMemory).not.toHaveBeenCalled()

    await wrapper.get('[data-testid="save-travel"]').trigger('click')
    await flushPromises()
    expect(wrapper.get('[data-testid="sync-ai-memory"]').attributes('disabled')).toBeUndefined()
    await wrapper.get('[data-testid="sync-ai-memory"]').trigger('click')
    await flushPromises()
    expect(syncSettingsToAiMemory).toHaveBeenCalledOnce()
  })

  it('shows the API error and re-enables the sync control after failure', async () => {
    syncSettingsToAiMemory.mockRejectedValue(new Error('同步失败'))
    const wrapper = await mountLoaded()
    await wrapper.get('[data-testid="sync-ai-memory"]').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('同步失败')
    expect(wrapper.get('[data-testid="sync-ai-memory"]').attributes('disabled')).toBeUndefined()
  })

  it('prevents duplicate AI memory sync requests while one is pending', async () => {
    let resolveSync!: () => void
    syncSettingsToAiMemory.mockReturnValue(new Promise<void>((resolve) => { resolveSync = resolve }))
    const wrapper = await mountLoaded()
    const button = wrapper.get('[data-testid="sync-ai-memory"]')

    await button.trigger('click')
    await button.trigger('click')

    expect(syncSettingsToAiMemory).toHaveBeenCalledOnce()
    expect(button.attributes('disabled')).toBeDefined()
    resolveSync()
    await flushPromises()
  })

  it('disables only the notification categories when the master switch is off', async () => {
    const wrapper = await mountLoaded()
    const switches = wrapper.findAll('input[role="switch"]')
    await switches[0].setValue(false)
    expect((switches[1].element as HTMLInputElement).disabled).toBe(true)
    expect((switches[1].element as HTMLInputElement).checked).toBe(true)
  })

  it('saves profile and privacy sections through their intended APIs', async () => {
    const wrapper = await mountLoaded()
    await wrapper.get('input[name="nickname"]').setValue('新名字')
    await wrapper.get('[data-testid="save-profile"]').trigger('click')
    await flushPromises()
    expect(updateMyProfile).toHaveBeenCalledWith({ nickname: '新名字', avatar_asset_id: null })
    await wrapper.get('input[value="private"]').setValue(true)
    await wrapper.get('[data-testid="save-privacy"]').trigger('click')
    await flushPromises()
    expect(updateMySettings).toHaveBeenCalledWith({ profile_visibility: 'private' })
  })

  it('requests browser confirmation when an edited section has unsaved changes', async () => {
    const wrapper = await mountLoaded()
    await wrapper.get('input[name="departure-city"]').setValue('上海')
    const event = new Event('beforeunload', { cancelable: true })
    window.dispatchEvent(event)
    expect(event.defaultPrevented).toBe(true)
  })
})
