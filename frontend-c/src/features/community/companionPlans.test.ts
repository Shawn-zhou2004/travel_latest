import { beforeEach, describe, expect, it, vi } from 'vitest'
import { acceptCompanionApplication, acceptedDestination, applyToCompanionPlan, canPublishPlan, listCompanionPlans, publishCompanionPlan, publishPayload, remainingSeats, requiresDestinationSelection, updateCompanionPlan, type CompanionPlanSummary } from './companionPlansApi'
import { routes } from '@/router'

const { api } = vi.hoisted(() => ({ api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() } }))

vi.mock('@/services/api', () => ({ api }))

describe('companion plan API', () => {
  beforeEach(() => vi.clearAllMocks())

  it('formats remaining seats from accepted count and party size', () => {
    expect(remainingSeats({ accepted_count: 2, party_size: 4 } as CompanionPlanSummary)).toBe(2)
  })

  it('submits a required application message', async () => {
    api.post.mockResolvedValue({ data: { id: 'application-1', status: 'pending' } })

    await applyToCompanionPlan('plan-1', 'I enjoy early walks and food markets.')

    expect(api.post).toHaveBeenCalledWith('/companion-requests/plan-1/applications', {
      message: 'I enjoy early walks and food markets.',
    })
  })

  it('uses the paginated companion plan discovery contract', async () => {
    api.get.mockResolvedValue({ data: { items: [], next_cursor: null } })

    await listCompanionPlans({ city_code: '330100', trip_kind: 'trip', has_slots: true })

    expect(api.get).toHaveBeenCalledWith('/companion-requests', {
      params: { city_code: '330100', trip_kind: 'trip', has_slots: true },
    })
  })

  it('requires capacity, pace, tags, and intro before publishing a companion plan', () => {
    expect(canPublishPlan({ partySize: 1, pace: 'slow', tags: ['citywalk'], intro: 'Hello' })).toBe(false)
    expect(canPublishPlan({ partySize: 3, pace: 'balanced', tags: ['citywalk'], intro: 'Travel slowly.' })).toBe(true)
  })

  it('publishes only companion metadata for an existing itinerary', async () => {
    api.post.mockResolvedValue({ data: { id: 'plan-1' } })
    const body = { party_size: 3, budget_min: null, budget_max: null, currency: null, travel_pace: 'slow' as const, interest_tags: ['citywalk'], intro_text: 'Walk together.' }
    await publishCompanionPlan('itinerary-1', body)
    expect(api.post).toHaveBeenCalledWith('/itineraries/itinerary-1/companion-requests', body)
  })

  it('requires a selected city only when the itinerary has no inferred city', () => {
    expect(requiresDestinationSelection({ destination: { city_code: '330100' } })).toBe(false)
    expect(requiresDestinationSelection({ days: [{ events: [{ poi_snapshot: { city: '330100' } }] }] })).toBe(false)
    expect(requiresDestinationSelection({ days: [{ events: [{ poi_snapshot: {} }] }] })).toBe(true)
  })

  it('includes the selected internal code but not a free-text city name in the publish payload', () => {
    const form = { party_size: 3, budget_min: null, budget_max: null, currency: null, travel_pace: 'slow' as const, interest_tags: ['citywalk'], intro_text: 'Walk together.' }

    expect(publishPayload(form, { city_code: '330100' })).toMatchObject({ city_code: '330100' })
    expect(publishPayload(form, null)).not.toHaveProperty('city_name')
    expect(publishPayload(form, null)).not.toHaveProperty('city_code')
  })

  it('updates owner-editable public companion metadata', async () => {
    api.patch.mockResolvedValue({ data: { id: 'plan-1', status: 'open' } })
    const body = { party_size: 4, budget_min: 800, budget_max: 1200, currency: 'CNY', travel_pace: 'packed' as const, interest_tags: ['food'], intro_text: 'Updated details.' }

    await updateCompanionPlan('plan-1', body)

    expect(api.patch).toHaveBeenCalledWith('/companion-requests/plan-1', body)
  })

  it('routes accepted members into the group conversation', () => {
    expect(acceptedDestination({ conversation_id: 'conversation-1' })).toBe('/messages/conversation-1')
  })

  it('sends group profile only when supplied for first acceptance', async () => {
    api.post.mockResolvedValue({ data: { conversation_id: 'conversation-1' } })
    await acceptCompanionApplication('application-1', '西湖慢行小组', 'asset-1')
    expect(api.post).toHaveBeenCalledWith('/companion-applications/application-1:accept', { group_name: '西湖慢行小组', group_avatar_asset_id: 'asset-1' })
    api.post.mockClear()
    await acceptCompanionApplication('application-2')
    expect(api.post).toHaveBeenCalledWith('/companion-applications/application-2:accept', undefined)
  })
})

describe('companion plan routes', () => {
  it('registers public discovery and detail routes', () => {
    expect(routes.find((route) => route.path === '/companions')?.component).toBeDefined()
    expect(routes.find((route) => route.path === '/companions/:requestId')?.component).toBeDefined()
    expect(routes.find((route) => route.path === '/companions/publish-activity')?.meta?.requiresConsumer).toBe(true)
    expect(routes.find((route) => route.path === '/itineraries/:itineraryId/publish-companion-plan')?.meta?.requiresConsumer).toBe(true)
  })
})
