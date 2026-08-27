import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const { getItinerary, getCompanionWorkspace, removeItineraryDay, deleteItinerary, workspace } = vi.hoisted(() => {
  const { reactive } = require('vue')
  const workspace = reactive({
    itineraryId: '', version: 1, snapshot: null as any, state: 'loading', routeUpdating: false, accessRole: 'owner',
    canEdit: true, eventIds: [],
    setSnapshot: vi.fn(), setEvents: vi.fn(), recalculateRoute: vi.fn(), apply: vi.fn(),
  })
  workspace.setSnapshot.mockImplementation((snapshot: { days: unknown[] }, version: number) => {
    workspace.snapshot = snapshot
    workspace.version = version
    workspace.state = snapshot.days.length ? 'saved' : 'empty'
  })
  return { getItinerary: vi.fn(), getCompanionWorkspace: vi.fn(), removeItineraryDay: vi.fn(), deleteItinerary: vi.fn(), workspace }
})

vi.mock('@/services/api', () => ({ normalizeApiError: (error: { code?: string }) => ({ code: error.code ?? 'REQUEST_FAILED' }) }))
vi.mock('../api', () => ({ acceptCollaborator: vi.fn(), createShareToken: vi.fn(), deleteItinerary, getCompanionWorkspace, getItinerary, inviteCollaborator: vi.fn(), listItineraryVersions: vi.fn(), removeItineraryDay, searchPOIs: vi.fn() }))
vi.mock('vue-router', () => ({ RouterLink: { template: '<a><slot /></a>' }, useRoute: () => ({ query: {} }), useRouter: () => ({ push: vi.fn() }) }))
vi.mock('../stores/itinerary', () => ({ useItineraryStore: () => workspace }))
vi.mock('../stores/export', () => ({ useItineraryExportStore: () => ({ reset: vi.fn(), state: 'idle' }) }))

import ItineraryWorkspacePage from './ItineraryWorkspacePage.vue'

describe('ItineraryWorkspacePage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    workspace.itineraryId = ''
    workspace.version = 1
    workspace.snapshot = null
    workspace.state = 'loading'
    workspace.routeUpdating = false
    workspace.accessRole = 'owner'
    workspace.canEdit = true
    workspace.eventIds = []
    getCompanionWorkspace.mockResolvedValue(null)
  })
  it('hides the workspace controls when a private itinerary is unavailable to the current user', async () => {
    getItinerary.mockRejectedValueOnce({ code: 'ITINERARY_NOT_FOUND' })
    const wrapper = mount(ItineraryWorkspacePage, {
      props: { itineraryId: '935d0e62-37d0-4622-be77-e1397fa12722' },
      global: { stubs: { Timeline: true, MapPanel: true, TripSupportPanel: true } },
    })

    await flushPromises()

    expect(wrapper.text()).toContain('这份行程暂时不可访问。')
    expect(wrapper.text()).not.toContain('加入第一天')
    expect(wrapper.find('[aria-label="导出 DOCX"]').exists()).toBe(false)
    expect(wrapper.find('[aria-label="Share itinerary"]').exists()).toBe(false)
  })

  it('removes a selected day through the versioned operation and selects the previous surviving day', async () => {
    getItinerary.mockResolvedValueOnce({
      title: '杭州三日游', version: 3, access_role: 'editor', source_post_id: null,
      snapshot: { title: '杭州三日游', start_date: '2026-08-12', end_date: '2026-08-14', days: [
        { id: 'day-1', day_date: '2026-08-12', display_order: 0, events: [] },
        { id: 'day-2', day_date: '2026-08-13', display_order: 1, events: [] },
        { id: 'day-3', day_date: '2026-08-14', display_order: 2, events: [] },
      ] },
    })
    removeItineraryDay.mockResolvedValueOnce({ code: 'APPLIED', current_version: 4, snapshot: { title: '杭州三日游', start_date: '2026-08-12', end_date: '2026-08-14', days: [
      { id: 'day-1', day_date: '2026-08-12', display_order: 0, events: [] },
      { id: 'day-3', day_date: '2026-08-14', display_order: 1, events: [] },
    ] } })

    const wrapper = mount(ItineraryWorkspacePage, { props: { itineraryId: 'trip-1' }, global: { stubs: { Timeline: true, MapPanel: true, TripSupportPanel: true } } })
    await flushPromises()
    await wrapper.findAll('.day-select')[1].trigger('click')
    await wrapper.findAll('[aria-label="删除这一天"]')[1].trigger('click')
    await wrapper.get('button.delete-confirm').trigger('click')
    await flushPromises()

    expect(removeItineraryDay).toHaveBeenCalledWith('trip-1', 3, expect.any(String), 'day-2')
    expect(wrapper.findAll('.day-entry.selected')[0].text()).toContain('DAY 01')
  })

  it('shows the owner-only plan deletion confirmation and deletes without title input', async () => {
    getItinerary.mockResolvedValueOnce({ title: '杭州三日游', version: 1, access_role: 'owner', source_post_id: null, snapshot: { title: '杭州三日游', start_date: '2026-08-12', end_date: '2026-08-12', days: [] } })
    const wrapper = mount(ItineraryWorkspacePage, { props: { itineraryId: 'trip-1' }, global: { stubs: { Timeline: true, MapPanel: true, TripSupportPanel: true } } })
    await flushPromises()
    await wrapper.get('.more-actions summary').trigger('click')
    await wrapper.get('.more-actions button').trigger('click')
    expect(wrapper.get('#delete-itinerary-title').text()).toBe('删除计划')
    expect(wrapper.find('.delete-dialog input').exists()).toBe(false)
    expect(wrapper.get('button.delete-confirm').attributes('disabled')).toBeUndefined()
    await wrapper.get('button.delete-confirm').trigger('click')
    await flushPromises()
    expect(deleteItinerary).toHaveBeenCalledWith('trip-1')
  })

  it('hides companion lifecycle actions until review approval', async () => {
    getItinerary.mockResolvedValueOnce({ title: '杭州三日游', version: 1, access_role: 'owner', source_post_id: null, snapshot: { title: '杭州三日游', start_date: '2026-08-12', end_date: '2026-08-12', days: [] } })
    getCompanionWorkspace.mockResolvedValueOnce({ id: 'plan-1', status: 'open', review_status: 'pending_review', party_size: 3, accepted_count: 1, role: 'owner', conversation_id: null })
    const wrapper = mount(ItineraryWorkspacePage, { props: { itineraryId: 'trip-1' }, global: { stubs: { Timeline: true, MapPanel: true, TripSupportPanel: true } } })
    await flushPromises()

    expect(wrapper.text()).not.toContain('关闭招募')
    expect(wrapper.text()).not.toContain('结束同行')
  })

  it('shows companion lifecycle actions after review approval', async () => {
    getItinerary.mockResolvedValueOnce({ title: '杭州三日游', version: 1, access_role: 'owner', source_post_id: null, snapshot: { title: '杭州三日游', start_date: '2026-08-12', end_date: '2026-08-12', days: [] } })
    getCompanionWorkspace.mockResolvedValueOnce({ id: 'plan-1', status: 'open', review_status: 'approved', party_size: 3, accepted_count: 1, role: 'owner', conversation_id: null })
    const wrapper = mount(ItineraryWorkspacePage, { props: { itineraryId: 'trip-1' }, global: { stubs: { Timeline: true, MapPanel: true, TripSupportPanel: true } } })
    await flushPromises()

    expect(wrapper.text()).toContain('关闭招募')
    expect(wrapper.text()).toContain('结束同行')
  })
})
