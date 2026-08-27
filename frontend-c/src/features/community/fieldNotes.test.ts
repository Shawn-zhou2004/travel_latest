import { beforeEach, describe, expect, it, vi } from 'vitest'
import { canPublish, copyDestination, copyFieldNote, getFieldNote, listFieldNotes, listMyFieldNotes, routeMeta } from './fieldNotesApi'
import { publishFieldNote } from '@/features/itineraries/api'
import { routes } from '@/router'

const { api } = vi.hoisted(() => ({ api: { get: vi.fn(), post: vi.fn() } }))

vi.mock('@/services/api', () => ({ api }))

describe('field note API', () => {
  beforeEach(() => vi.clearAllMocks())

  it('lists only itinerary field notes with supported filters', async () => {
    api.get.mockResolvedValue({ data: { items: [], next_cursor: null } })

    await listFieldNotes({ city_code: '330100', q: 'West Lake', sort: 'recommended' })

    expect(api.get).toHaveBeenCalledWith('/posts', {
      params: { content_type: 'itinerary', city_code: '330100', q: 'West Lake', sort: 'recommended' },
    })
  })

  it('reads a field note by its public post ID', async () => {
    api.get.mockResolvedValue({ data: { id: 'post-1' } })

    await getFieldNote('post-1')

    expect(api.get).toHaveBeenCalledWith('/posts/post-1')
  })

  it('copies a published field note with an idempotency key', async () => {
    api.post.mockResolvedValue({ data: { itinerary: { id: 'trip-1' }, source_post_id: 'post-1', idempotent: false } })

    await copyFieldNote('post-1', 'retry-key')

    expect(api.post).toHaveBeenCalledWith('/posts/post-1:copy-itinerary', {}, {
      headers: { 'Idempotency-Key': 'retry-key' },
    })
  })

  it('publishes the selected itinerary version and image IDs', async () => {
    api.post.mockResolvedValue({ data: { id: 'post-1' } })
    const payload = { version_no: 2, title: 'West Lake', recap_text: 'Go early.', cover_media_id: 'asset-1', media_ids: ['asset-1'] }

    await publishFieldNote('trip-1', payload)

    expect(api.post).toHaveBeenCalledWith('/itineraries/trip-1/field-notes', payload)
  })

  it('reads author field notes from the private status endpoint', async () => {
    api.get.mockResolvedValue({ data: [] })
    await listMyFieldNotes()
    expect(api.get).toHaveBeenCalledWith('/posts/me/field-notes')
  })
})

describe('field note routes', () => {
  it('registers public detail and authenticated publish routes', () => {
    expect(routes.map((route) => route.path)).toContain('/community/:postId')
    expect(routes.find((route) => route.path === '/itineraries/:itineraryId/publish-field-note')?.meta).toMatchObject({ requiresConsumer: true })
  })

  it('registers the field-note archive on the public community route', () => {
    expect(routes.find((route) => route.path === '/community')?.component).toBeDefined()
  })

  it('registers the authenticated author status route', () => {
    expect(routes.find((route) => route.path === '/community/mine')?.meta).toMatchObject({ requiresConsumer: true })
  })
})

describe('field note view models', () => {
  it('requires a selected version, recap, cover, and at least one uploaded image', () => {
    expect(canPublish({ versionNo: null, title: 'Quiet Hangzhou', recap: 'Text', coverId: 'asset-1', mediaIds: ['asset-1'] })).toBe(false)
    expect(canPublish({ versionNo: 2, title: 'Quiet Hangzhou', recap: 'Text', coverId: 'asset-1', mediaIds: ['asset-1'] })).toBe(true)
    expect(canPublish({ versionNo: 2, title: 'Quiet Hangzhou', recap: 'Text', coverId: 'missing', mediaIds: ['asset-1'] })).toBe(false)
  })

  it('formats route metadata from the frozen snapshot', () => {
    expect(routeMeta({ days: [{ events: [{}, {}] }, { events: [{}] }] } as never)).toEqual({ days: 2, stops: 3 })
  })

  it('uses the detail copy result route', () => {
    expect(copyDestination({ itinerary: { id: 'trip-2' } } as never)).toBe('/itineraries/trip-2')
  })
})
