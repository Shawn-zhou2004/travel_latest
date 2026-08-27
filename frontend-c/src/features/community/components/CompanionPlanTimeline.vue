<script setup lang="ts">
import { MapPinned, Route } from 'lucide-vue-next'
import type { ItinerarySnapshot } from '../companionPlansApi'

defineProps<{ routeCount: number; itinerary?: ItinerarySnapshot }>()
</script>

<template>
  <section class="timeline" aria-label="路线概览">
    <header><Route :size="17" /><div><p>ROUTE CONTEXT</p><h2>{{ itinerary ? '共同路线' : '公开路线概览' }}</h2></div><strong>{{ routeCount }} 站</strong></header>
    <ol v-if="itinerary?.days?.length" class="days">
      <li v-for="(day, dayIndex) in itinerary.days" :key="`${day.date || 'day'}-${dayIndex}`"><span class="day">D{{ dayIndex + 1 }}</span><div><strong>{{ day.title || day.date || `第 ${dayIndex + 1} 天` }}</strong><ul><li v-for="(event, eventIndex) in day.events || []" :key="`${event.title || 'stop'}-${eventIndex}`"><MapPinned :size="14" />{{ event.title || event.poi_snapshot?.name || '路线停靠点' }}</li></ul></div></li>
    </ol>
    <p v-else class="public-route"><MapPinned :size="16" />发起人已规划 {{ routeCount }} 个公开路线节点。加入后可查看协作路线详情。</p>
  </section>
</template>

<style scoped>
/* ============ 容器 ============ */
.timeline {
  animation: settle var(--motion-base) var(--ease-out) both;
  border-top: 2px solid var(--field-ink);
  padding-top: 18px;
}

.timeline header {
  align-items: center;
  display: flex;
  gap: 10px;
}

.timeline header > svg { color: var(--field-coral); }

.timeline p {
  color: var(--field-teal);
  font: 800 10px var(--field-mono);
  letter-spacing: .1em;
  margin: 0;
}

.timeline h2 { font-size: 19px; margin: 3px 0 0; }

.timeline header strong {
  color: var(--field-muted);
  font: 700 11px var(--field-mono);
  margin-left: auto;
}

/* ============ 日程列表 ============ */
.days {
  display: grid;
  gap: 16px;
  list-style: none;
  margin: 22px 0 0;
  padding: 0;
}

.days > li {
  display: grid;
  gap: 12px;
  grid-template-columns: 30px 1fr;
}

.day { color: var(--field-coral); font: 800 12px var(--field-mono); }

.days strong { color: var(--field-ink); font-size: 14px; }

.days ul {
  display: grid;
  gap: 7px;
  list-style: none;
  margin: 8px 0 0;
  padding: 0;
}

.days ul li,
.public-route {
  align-items: center;
  color: var(--field-ink-soft);
  display: flex;
  font-size: 13px;
  gap: 7px;
  line-height: 1.5;
}

.days ul svg,
.public-route svg { color: var(--field-teal); flex: 0 0 auto; }

.public-route {
  background: var(--travel-sky);
  margin: 20px 0 0;
  padding: 15px;
}

@keyframes settle {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: translateY(0); }
}

@media (prefers-reduced-motion: reduce) {
  .timeline { animation: none; }
}
</style>
