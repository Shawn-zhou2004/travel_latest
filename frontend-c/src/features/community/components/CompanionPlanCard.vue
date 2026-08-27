<script setup lang="ts">
import { ArrowUpRight, CalendarDays, MapPin, Route, Users } from 'lucide-vue-next'
import { RouterLink } from 'vue-router'
import { formatBudget, remainingSeats, type CompanionPlanSummary } from '../companionPlansApi'

const props = defineProps<{ plan: CompanionPlanSummary; featured?: boolean; index?: number }>()

function dateRange(plan: CompanionPlanSummary) {
  if (!plan.start_date) return '日期待定'
  return plan.end_date && plan.end_date !== plan.start_date ? `${plan.start_date} - ${plan.end_date}` : plan.start_date
}

function stateLabel(plan: CompanionPlanSummary) {
  if (plan.application_status === 'pending') return '申请已提交'
  if (plan.application_status === 'accepted') return '已加入'
  if (plan.status === 'full') return '已满员'
  if (plan.status === 'closed') return '已结束招募'
  if (plan.status === 'completed') return '行程已完成'
  return `${remainingSeats(plan)} 个名额`
}
</script>

<template>
  <article class="plan-card" :class="{ featured }" :style="{ '--entry-delay': `${(index ?? 0) * 55}ms` }">
    <div class="card-number">{{ String((index ?? 0) + 1).padStart(2, '0') }}</div>
    <div class="card-body">
      <div class="card-topline"><span>{{ plan.trip_kind === 'activity' ? '短途活动' : '同行路线' }}</span><span :class="`status status-${plan.status}`">{{ stateLabel(plan) }}</span></div>
      <h2><RouterLink :to="`/companions/${plan.id}`">{{ plan.title }}</RouterLink></h2>
      <p class="intro">{{ plan.intro_text || '路线信息正在整理中。' }}</p>
      <dl class="facts">
        <div><dt><MapPin :size="15" />目的地</dt><dd>{{ plan.city_code || '待定' }}</dd></div>
        <div><dt><CalendarDays :size="15" />出发</dt><dd>{{ dateRange(plan) }}</dd></div>
        <div><dt><Users :size="15" />同行</dt><dd>{{ plan.accepted_count }} / {{ plan.party_size ?? '-' }} 人</dd></div>
        <div><dt><Route :size="15" />路线</dt><dd>{{ plan.route_count }} 站</dd></div>
      </dl>
      <div class="tags"><span v-for="tag in plan.interest_tags" :key="tag">{{ tag }}</span><small>{{ plan.travel_pace || '节奏待定' }} · {{ formatBudget(plan) }}</small></div>
    </div>
    <RouterLink class="card-link" :to="`/companions/${plan.id}`" :aria-label="`查看 ${plan.title}`"><ArrowUpRight :size="20" /></RouterLink>
  </article>
</template>

<style scoped>
/* ============ 卡片容器 ============ */
.plan-card {
  animation: settle var(--motion-base) var(--ease-out) both;
  animation-delay: var(--entry-delay, 0ms);
  border-top: 1px solid var(--field-line);
  display: grid;
  gap: 20px;
  grid-template-columns: 46px minmax(0, 1fr) 38px;
  padding: 25px 0;
}

.plan-card.featured {
  border-top: 2px solid var(--field-ink);
  padding-top: 30px;
}

.card-number,
.card-topline {
  color: var(--field-teal);
  font: 800 11px var(--field-mono);
  letter-spacing: .08em;
}

.card-body { min-width: 0; }

.card-topline {
  display: flex;
  gap: 12px;
  justify-content: space-between;
}

.status { color: var(--field-muted); }
.status-full,
.status-closed,
.status-completed { color: var(--field-coral); }

/* ============ 标题 ============ */
.plan-card h2 {
  font-size: clamp(23px, 3vw, 34px);
  line-height: 1.15;
  margin: 8px 0;
}

.plan-card h2 a {
  color: var(--field-ink);
  text-decoration: none;
  transition: color var(--motion-fast) var(--ease-standard);
}

.plan-card h2 a:hover { color: var(--field-teal); }
.plan-card h2 a:focus-visible { outline: 3px solid var(--field-saffron); outline-offset: 3px; }

.intro {
  color: var(--field-ink-soft);
  line-height: 1.65;
  margin: 0;
  max-width: 720px;
}

/* ============ 概要事实 ============ */
.facts {
  display: grid;
  gap: 12px 18px;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  margin: 19px 0;
}

.facts div { min-width: 0; }

.facts dt {
  align-items: center;
  color: var(--field-muted);
  display: flex;
  font: 700 10px var(--field-mono);
  gap: 5px;
  letter-spacing: .06em;
}

.facts dd {
  color: var(--field-ink);
  font-size: 13px;
  margin: 5px 0 0;
  overflow-wrap: anywhere;
}

/* ============ 标签 ============ */
.tags {
  align-items: center;
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
}

.tags span {
  background: var(--field-teal-soft);
  color: var(--field-teal);
  font: 700 10px var(--field-mono);
  padding: 5px 7px;
}

.tags small {
  color: var(--field-muted);
  font: 700 11px var(--field-mono);
  margin-left: 4px;
}

/* ============ 跳转入口 ============ */
.card-link {
  align-self: start;
  border: 1px solid var(--field-line);
  color: var(--field-ink);
  display: grid;
  height: 36px;
  place-items: center;
  transition: background-color var(--motion-fast) var(--ease-standard), color var(--motion-fast) var(--ease-standard), transform var(--motion-fast) var(--ease-standard), box-shadow var(--motion-fast) var(--ease-standard);
  width: 36px;
}

.card-link:hover {
  background: var(--field-ink);
  color: #fff;
  transform: translateY(-1px);
  box-shadow: var(--shadow-soft);
}

.card-link:focus-visible {
  background: var(--field-ink);
  color: #fff;
  outline: 3px solid var(--field-saffron);
  outline-offset: 2px;
}

.card-link:active { transform: translateY(0) scale(0.94); }

@keyframes settle {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: translateY(0); }
}

/* ============ 响应式 ============ */
@media (max-width: 650px) {
  .plan-card { gap: 13px; grid-template-columns: 30px minmax(0, 1fr); }
  .card-link { grid-column: 2; }
  .facts { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .card-topline { align-items: flex-start; flex-direction: column; gap: 4px; }
}

@media (prefers-reduced-motion: reduce) {
  .plan-card { animation: none; }
  .plan-card h2 a,
  .card-link { transition: none; }
  .card-link:hover { transform: none; }
}
</style>
