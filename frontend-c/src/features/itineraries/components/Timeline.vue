<script setup lang="ts">
import { ArrowDown, ArrowUp, CircleDot, Trash2 } from 'lucide-vue-next'
import type { ItineraryDay } from '../api'

const props = defineProps<{ day: ItineraryDay; active: boolean; selectedEventId?: string; busyEventId?: string; readonly?: boolean }>()
const emit = defineEmits<{
  select: [eventId: string]
  move: [eventId: string, direction: 'up' | 'down']
  remove: [eventId: string]
}>()
</script>

<template>
  <section class="timeline" :class="{ active }">
    <header class="timeline-header"><div><time>{{ day.day_date }}</time><strong>{{ active ? 'Selected day' : 'Planned day' }}</strong></div><span>{{ day.events.length }} stops</span></header>
    <TransitionGroup name="list" tag="ol">
      <li v-for="(event, index) in day.events" :key="event.id" :class="{ selected: props.selectedEventId === event.id }">
        <time class="event-time">{{ event.starts_at?.slice(11, 16) || 'Flexible' }}</time>
        <div class="event-card">
          <button class="event-main" type="button" :aria-pressed="props.selectedEventId === event.id" @click="emit('select', event.id!)">
            <span class="event-marker"><CircleDot :size="13" /></span>
            <span class="event-copy"><strong>{{ event.poi_snapshot.name || event.poi_id }}</strong><small>{{ event.poi_snapshot.address || 'Verified place' }}</small><em v-if="event.notes">{{ event.notes }}</em></span>
          </button>
          <div v-if="!props.readonly" class="event-actions" aria-label="Stop actions">
            <button type="button" title="Move stop up" aria-label="Move stop up" :disabled="index === 0 || props.busyEventId === event.id" @click="emit('move', event.id!, 'up')"><ArrowUp :size="14" /></button>
            <button type="button" title="Move stop down" aria-label="Move stop down" :disabled="index === day.events.length - 1 || props.busyEventId === event.id" @click="emit('move', event.id!, 'down')"><ArrowDown :size="14" /></button>
            <button type="button" title="Remove stop" aria-label="Remove stop" :disabled="props.busyEventId === event.id" @click="emit('remove', event.id!)"><Trash2 :size="14" /></button>
          </div>
        </div>
      </li>
      <li v-if="!day.events.length" key="empty" class="empty"><div><strong>No places yet</strong><small>Verified places will appear here in the order you choose.</small></div></li>
    </TransitionGroup>
  </section>
</template>

<style scoped>
.timeline { border-top: 1px solid var(--field-line); padding: 22px 0 30px; }.timeline:first-child { border-top: 0; }.timeline-header { align-items: end; display: flex; justify-content: space-between; }.timeline-header > div { align-items: baseline; display: flex; gap: 14px; }.timeline-header time { color: var(--field-teal); font: 800 12px/1 var(--field-mono); }.timeline-header strong { font-size: 15px; }.timeline-header > span { color: var(--field-muted); font: 11px var(--field-mono); }
ol { list-style: none; margin: 24px 0 0; padding: 0; }li { display: grid; grid-template-columns: 68px minmax(0, 1fr); gap: 14px; padding: 0 0 16px; position: relative; }li:not(:last-child)::before { background: #b7c7c8; content: ''; height: calc(100% - 10px); left: 73px; position: absolute; top: 21px; width: 1px; }.event-time { color: var(--field-saffron); font: 700 11px/20px var(--field-mono); }.event-card { align-items: stretch; background: #fff; border: 1px solid var(--field-line); display: flex; min-width: 0; transition: border-color .18s ease, box-shadow .18s ease; }.event-card:hover, li.selected .event-card { border-color: var(--field-teal); box-shadow: 0 8px 24px rgba(20, 38, 56, .08); }.event-main { align-items: start; background: transparent; border: 0; color: var(--field-ink); cursor: pointer; display: flex; flex: 1; gap: 12px; min-width: 0; padding: 15px 15px 15px 12px; text-align: left; }.event-marker { color: var(--field-coral); display: inline-flex; flex: 0 0 auto; margin-top: 2px; }.event-copy { display: grid; gap: 4px; min-width: 0; }.event-copy strong { font-size: 15px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }.event-copy small { color: var(--field-muted); font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }.event-copy em { color: var(--field-teal); font-size: 12px; font-style: normal; line-height: 1.4; margin-top: 3px; }.event-actions { align-items: center; border-left: 1px solid var(--field-line); display: flex; flex: 0 0 auto; gap: 2px; padding: 0 7px; }.event-actions button { align-items: center; background: transparent; border: 0; color: var(--field-muted); cursor: pointer; display: inline-flex; padding: 7px; }.event-actions button:hover { color: var(--field-teal); }.event-actions button:last-child:hover { color: var(--field-coral); }.event-actions button:disabled { cursor: default; opacity: .32; }.empty { align-items: center; background: #eef5f2; border: 1px dashed #a7c2be; display: flex; min-height: 118px; padding: 20px; }.empty strong, .empty small { display: block; }.empty small { color: var(--field-muted); font-size: 12px; margin-top: 5px; }
@media (max-width: 620px) { li { grid-template-columns: 1fr; gap: 6px; }.event-time { padding-left: 12px; }.timeline-header > div { align-items: start; flex-direction: column; gap: 6px; } }
@media (prefers-reduced-motion: reduce) { .event-card { transition: none; } }
/* Stops are route notes on a continuous line rather than independent utility cards. */
.timeline{--travel-ink:var(--field-ink);--travel-muted:var(--field-muted);--travel-line:var(--field-line);--travel-sea:var(--field-teal);--travel-coral:var(--field-coral);border-top-color:var(--travel-line);padding-top:26px;animation:reveal-soft var(--motion-slow) var(--ease-out) both}.timeline-header time{color:var(--travel-coral)}.timeline-header strong{font-family:Georgia,"Noto Serif SC",serif;font-size:20px;font-weight:600}.timeline-header>span{background:#edf7f2;border-radius:999px;color:var(--travel-sea);padding:5px 8px}ol{margin-top:26px}li{grid-template-columns:76px minmax(0,1fr);padding-bottom:18px}li:not(:last-child)::before{background:linear-gradient(var(--travel-sea),#c5ddd2);left:81px;top:23px}.event-time{color:var(--travel-coral)}.event-card{background:#fff;border-color:var(--travel-line);border-radius:10px;overflow:hidden}.event-card:hover,li.selected .event-card{border-color:var(--travel-sea);box-shadow:var(--shadow-soft)}.event-main{padding:17px 16px 17px 13px}.event-marker{color:var(--travel-sea)}.event-copy strong{font-family:Georgia,"Noto Serif SC",serif;font-size:17px;font-weight:600}.event-copy em{color:var(--travel-coral)}.event-actions{background:#f7fbf8;border-left-color:var(--travel-line)}.event-actions button{transition:color var(--motion-fast) var(--ease-standard),transform var(--motion-fast) var(--ease-standard)}.event-actions button:hover{color:var(--travel-sea)}.event-actions button:active:not(:disabled){transform:scale(.92)}.empty{background:#f3faf6;border-color:#b8d6c8;border-radius:10px}@media(max-width:620px){li{grid-template-columns:1fr}.event-time{padding-left:13px}li:not(:last-child)::before{display:none}.event-actions{padding:4px 7px}}@media (prefers-reduced-motion: reduce){.timeline{animation:none}.event-card,.event-actions button{transition:none}}
</style>
