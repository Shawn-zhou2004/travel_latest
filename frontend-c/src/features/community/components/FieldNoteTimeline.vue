<script setup lang="ts">
import { computed } from 'vue'
import { Clock3, MapPin } from 'lucide-vue-next'
import type { ItinerarySnapshot } from '@/features/itineraries/api'

const props = defineProps<{ snapshot: ItinerarySnapshot }>()
const days = computed(() => [...props.snapshot.days].sort((left, right) => left.display_order - right.display_order))

function eventName(event: ItinerarySnapshot['days'][number]['events'][number]) {
  return event.poi_snapshot.name || event.poi_id
}

function timeRange(startsAt: string | null, endsAt: string | null) {
  if (!startsAt) return '时间待定'
  const start = new Date(startsAt).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
  if (!endsAt) return start
  return `${start} - ${new Date(endsAt).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}`
}
</script>

<template>
  <section class="timeline" aria-label="公开行程路线">
    <header><p>ROUTE ARCHIVE</p><h2>行程记录</h2></header>
    <ol class="days">
      <li v-for="day in days" :key="`${day.day_date}-${day.display_order}`" class="day">
        <div class="day-marker"><span>DAY {{ String(day.display_order).padStart(2, '0') }}</span><time>{{ day.day_date }}</time></div>
        <ol class="stops">
          <li v-for="event in [...day.events].sort((left, right) => left.display_order - right.display_order)" :key="`${event.poi_id}-${event.display_order}`">
            <span class="stop-order">{{ String(event.display_order).padStart(2, '0') }}</span>
            <div><h3><MapPin :size="16" />{{ eventName(event) }}</h3><p v-if="event.poi_snapshot.address">{{ event.poi_snapshot.address }}</p><p v-if="event.notes" class="notes">{{ event.notes }}</p></div>
            <time><Clock3 :size="14" />{{ timeRange(event.starts_at, event.ends_at) }}</time>
          </li>
        </ol>
      </li>
    </ol>
  </section>
</template>

<style scoped>
.timeline { animation: fn-settle var(--motion-slow) var(--ease-out) both; border-top: 2px solid var(--field-ink); padding-top: 22px; }
@keyframes fn-settle { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: translateY(0); } }.timeline header p { color: var(--field-teal); font: 800 10px var(--field-mono); letter-spacing: .12em; margin: 0; }.timeline header h2 { font-size: 26px; margin: 7px 0 26px; }.days, .stops { list-style: none; margin: 0; padding: 0; }.day { display: grid; grid-template-columns: 138px 1fr; padding-bottom: 28px; }.day-marker { border-right: 1px solid var(--field-line); color: var(--field-ink); display: flex; flex-direction: column; font: 800 11px var(--field-mono); gap: 7px; letter-spacing: .06em; padding: 5px 18px 0 0; }.day-marker span { color: var(--field-saffron); }.day-marker time { color: var(--field-muted); font-size: 10px; }.stops { padding-left: 24px; }.stops li { border-bottom: 1px solid var(--field-line); display: grid; gap: 15px; grid-template-columns: 33px 1fr auto; padding: 0 0 18px; }.stops li + li { padding-top: 18px; }.stop-order { color: var(--field-saffron); font: 800 12px var(--field-mono); padding-top: 3px; }.stops h3 { align-items: center; color: var(--field-ink); display: flex; font-size: 16px; gap: 6px; margin: 0; }.stops h3 svg { color: var(--field-teal); }.stops p { color: var(--field-muted); font-size: 13px; line-height: 1.55; margin: 5px 0 0; }.stops .notes { color: var(--field-ink-soft); }.stops time { align-items: center; color: var(--field-muted); display: inline-flex; font: 700 11px var(--field-mono); gap: 5px; padding-top: 4px; white-space: nowrap; }
@media (max-width: 640px) { .day { display: block; }.day-marker { border-right: 0; border-bottom: 1px solid var(--field-line); flex-direction: row; justify-content: space-between; margin-bottom: 15px; padding: 0 0 11px; }.stops { padding-left: 0; }.stops li { gap: 10px; grid-template-columns: 28px 1fr; }.stops time { grid-column: 2; padding-top: 0; } }
@media (prefers-reduced-motion: reduce) { .timeline { animation: none; } }
</style>
