import { beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useItineraryStore } from './itinerary'

describe('itinerary workspace state', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('does not change event order when automatic route recalculation completes', async () => {
    const store = useItineraryStore()
    store.setEvents(['event-1', 'event-2'])
    await store.recalculateRoute('day-1')
    expect(store.eventIds).toEqual(['event-1', 'event-2'])
    expect(store.routeUpdating).toBe(false)
  })
})
