import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { applyItineraryOperation, getItinerary, getRouteCalculation, type ItineraryAccessRole, type ItinerarySnapshot, type OperationResult } from '../api'

export type WorkspaceState = 'loading' | 'empty' | 'saved' | 'conflict' | 'unavailable'

export const useItineraryStore = defineStore('itinerary-workspace', () => {
  const itineraryId = ref('')
  const version = ref(1)
  const snapshot = ref<ItinerarySnapshot | null>(null)
  const state = ref<WorkspaceState>('loading')
  const routeUpdating = ref(false)
  const accessRole = ref<ItineraryAccessRole>('owner')
  const canEdit = computed(() => accessRole.value === 'owner' || accessRole.value === 'editor')
  const eventIds = computed(() => snapshot.value?.days.flatMap((day) => [...day.events].sort((a, b) => a.display_order - b.display_order).map((event) => event.id)) ?? [])

  function setSnapshot(value: ItinerarySnapshot, nextVersion = version.value) {
    snapshot.value = { ...value, days: value.days.map((day) => ({ ...day, events: [...day.events].sort((a, b) => a.display_order - b.display_order) })) }
    version.value = nextVersion
    state.value = value.days.length ? 'saved' : 'empty'
  }

  function setEvents(ids: string[]) {
    const events = ids.map((id, display_order) => ({ id, poi_id: id, poi_snapshot: { name: id }, starts_at: null, ends_at: null, display_order, notes: null }))
    setSnapshot({ title: 'Untitled itinerary', start_date: '2026-10-01', end_date: '2026-10-01', days: [{ id: 'day-1', day_date: '2026-10-01', display_order: 0, events, route_segments: [] }] })
  }

  async function recalculateRoute(dayId: string) {
    if (!dayId || routeUpdating.value || !canEdit.value) return
    routeUpdating.value = true
    try {
      const result = await apply('recalculate_route', { day_id: dayId })
      if (result?.code !== 'APPLIED' || !result.route_job) return
      for (let attempt = 0; attempt < 30; attempt += 1) {
        await new Promise((resolve) => window.setTimeout(resolve, 1000))
        const job = await getRouteCalculation(itineraryId.value, result.route_job.id)
        if (job.status === 'queued' || job.status === 'calculating') continue
        const itinerary = await getItinerary(itineraryId.value)
        setSnapshot(itinerary.snapshot, itinerary.version)
        accessRole.value = itinerary.access_role
        if (job.status === 'failed') state.value = 'unavailable'
        return
      }
    } finally {
      routeUpdating.value = false
    }
  }

  async function apply(operationType: string, payload: Record<string, unknown>): Promise<OperationResult | undefined> {
    if (!itineraryId.value || !canEdit.value) return undefined
    try {
      const result = await applyItineraryOperation(itineraryId.value, version.value, crypto.randomUUID(), operationType, payload)
      if (result.code === 'APPLIED' && result.snapshot && result.current_version) setSnapshot(result.snapshot, result.current_version)
      else if (result.code === 'VERSION_CONFLICT') state.value = 'conflict'
      else if (result.code === 'MAP_UNAVAILABLE') state.value = 'unavailable'
      return result
    } catch {
      state.value = 'unavailable'
      return undefined
    }
  }

  return { itineraryId, version, snapshot, state, routeUpdating, accessRole, canEdit, eventIds, setSnapshot, setEvents, recalculateRoute, apply }
})
