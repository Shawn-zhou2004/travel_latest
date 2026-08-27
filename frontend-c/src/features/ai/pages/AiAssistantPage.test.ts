import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import AiAssistantPage from './AiAssistantPage.vue'

const { createAiConversation, createAiMemory, deleteAiMemory, listAiConversations, listAiMemories, listAiMessages, updateAiMemory } = vi.hoisted(() => ({
  createAiConversation: vi.fn(), createAiMemory: vi.fn(), deleteAiMemory: vi.fn(), listAiConversations: vi.fn(), listAiMemories: vi.fn(), listAiMessages: vi.fn(), updateAiMemory: vi.fn(),
}))

vi.mock('../assistantApi', () => ({
  createAiConversation, createAiMemory, deleteAiMemory, listAiConversations, listAiMemories, listAiMessages, updateAiMemory,
  deleteAiConversation: vi.fn(), replayAiAssistantRun: vi.fn(), streamAiAssistant: vi.fn(),
}))
const { listItineraries } = vi.hoisted(() => ({ listItineraries: vi.fn() }))
const { getMySettings } = vi.hoisted(() => ({ getMySettings: vi.fn() }))
vi.mock('@/features/itineraries/api', () => ({ listItineraries }))
vi.mock('@/features/settings/api', () => ({ getMySettings }))
vi.mock('@/composables/useReveal', () => ({ useReveal: vi.fn() }))
vi.mock('element-plus/es/components/message/index', () => ({ ElMessage: { success: vi.fn(), error: vi.fn() } }))

const memory = { id: 'memory-1', memory_type: 'profile' as const, memory_key: '饮食偏好', memory_value: { text: '少辣' }, source: 'user', confidence: 1, created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z' }

async function mountPage(memories: typeof memory[] = []) {
  const pinia = createPinia()
  setActivePinia(pinia)
  const wrapper = mount(AiAssistantPage, {
    global: {
      plugins: [pinia],
      stubs: {
        RouterLink: { template: '<a><slot /></a>' },
        ElDialog: { props: ['modelValue'], template: '<div v-if="modelValue"><slot /><slot name="footer" /></div>' },
      },
    },
  })
  await flushPromises()
  return wrapper
}

describe('AiAssistantPage memory management', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    listAiConversations.mockResolvedValue([])
    listAiMemories.mockResolvedValue([])
    listAiMessages.mockResolvedValue([])
    listItineraries.mockResolvedValue([])
    getMySettings.mockResolvedValue(null)
    createAiConversation.mockResolvedValue({ id: 'conversation-1', title: '旅行助手', created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z' })
    createAiMemory.mockResolvedValue({ ...memory, memory_value: { text: '不吃辣' } })
  })

  it('keeps the empty-memory copy visible when no memory exists', async () => {
    const wrapper = await mountPage()
    expect(wrapper.text()).toContain('尚无保存的旅行偏好。')
  })

  it('creates a profile memory from the memory form', async () => {
    const wrapper = await mountPage()
    await wrapper.get('[aria-label="新增记忆"]').trigger('click')
    await wrapper.get('input[name="memory-key"]').setValue('饮食偏好')
    await wrapper.get('textarea[name="memory-text"]').setValue('不吃辣')
    await wrapper.get('form[aria-label="新增记忆表单"]').trigger('submit')
    await flushPromises()

    expect(createAiMemory).toHaveBeenCalledWith('profile', '饮食偏好', '不吃辣')
    expect(wrapper.text()).toContain('不吃辣')
  })

  it('updates a memory with text instead of raw JSON', async () => {
    listAiMemories.mockResolvedValue([memory])
    updateAiMemory.mockResolvedValue({ ...memory, memory_value: { text: '不吃辣' } })
    const wrapper = await mountPage()
    await wrapper.get('[aria-label="编辑记忆"]').trigger('click')
    await wrapper.get('textarea[name="memory-text"]').setValue('不吃辣')
    await wrapper.get('form[aria-label="编辑记忆表单"]').trigger('submit')
    await flushPromises()

    expect(updateAiMemory).toHaveBeenCalledWith(memory.id, { text: '不吃辣' }, 'user', memory.confidence)
    expect(wrapper.text()).toContain('不吃辣')
  })

  it('removes a memory after deletion succeeds', async () => {
    listAiMemories.mockResolvedValue([memory])
    const wrapper = await mountPage()
    await wrapper.get('[aria-label="删除记忆"]').trigger('click')
    await flushPromises()

    expect(deleteAiMemory).toHaveBeenCalledWith(memory.id)
    expect(wrapper.text()).toContain('尚无保存的旅行偏好。')
  })

  it('keeps the form open and shows an API error after creation fails', async () => {
    createAiMemory.mockRejectedValue(Object.assign(new Error('保存失败'), { code: 'MEMORY_SAVE_FAILED' }))
    const wrapper = await mountPage()
    await wrapper.get('[aria-label="新增记忆"]').trigger('click')
    await wrapper.get('input[name="memory-key"]').setValue('饮食偏好')
    await wrapper.get('textarea[name="memory-text"]').setValue('不吃辣')
    await wrapper.get('form[aria-label="新增记忆表单"]').trigger('submit')
    await flushPromises()

    expect(wrapper.find('form[aria-label="新增记忆表单"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('保存失败')
  })
})
