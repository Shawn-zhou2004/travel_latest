<script setup lang="ts">
import { computed, ref } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import { ArrowLeft, Check, MapPin, Search, Send } from 'lucide-vue-next'
import { canPublishPlan, companionInterestTags, publishCompanionActivity, type CompanionPace } from './companionPlansApi'
import { searchPOIs, type POIRecord } from '@/features/itineraries/api'
import { useReveal } from '@/composables/useReveal'

const router = useRouter()
const title = ref(''); const city = ref(''); const date = ref(''); const startsAt = ref(''); const endsAt = ref('')
const query = ref(''); const results = ref<POIRecord[]>([]); const poi = ref<POIRecord>(); const searching = ref(false)
const partySize = ref(3); const budgetMin = ref<number | null>(null); const budgetMax = ref<number | null>(null); const currency = ref('CNY'); const pace = ref<CompanionPace>('balanced'); const tags = ref<string[]>(['citywalk']); const intro = ref(''); const error = ref(''); const submitting = ref(false)
const root = ref<HTMLElement | null>(null)
useReveal(root)
const invalid = computed(() => !title.value.trim() || !city.value.trim() || !date.value || !startsAt.value || !endsAt.value || !poi.value || !canPublishPlan({ partySize: partySize.value, pace: pace.value, tags: tags.value, intro: intro.value }) || (budgetMin.value === null) !== (budgetMax.value === null))
function toggleTag(tag: string) { tags.value = tags.value.includes(tag) ? tags.value.filter((item) => item !== tag) : tags.value.length < 8 ? [...tags.value, tag] : tags.value }
async function search() { if (!query.value.trim() || searching.value) return; searching.value = true; error.value = ''; try { results.value = await searchPOIs(query.value.trim(), city.value.trim() || undefined) } catch { error.value = '地点验证暂不可用，请稍后重试。' } finally { searching.value = false } }
async function submit() { if (submitting.value || invalid.value || !poi.value) return; submitting.value = true; error.value = ''; try { const plan = await publishCompanionActivity({ title: title.value.trim(), city_code: city.value.trim(), activity_date: date.value, starts_at: `${date.value}T${startsAt.value}:00`, ends_at: `${date.value}T${endsAt.value}:00`, poi_id: poi.value.id, party_size: partySize.value, budget_min: budgetMin.value, budget_max: budgetMax.value, currency: budgetMin.value === null ? null : currency.value, travel_pace: pace.value, interest_tags: tags.value, intro_text: intro.value.trim() }); await router.push(`/companions/${plan.id}`) } catch (reason) { error.value = reason instanceof Error ? reason.message : '活动同行计划暂未提交。' } finally { submitting.value = false } }
</script>

<template>
  <main class="publish-page" ref="root"><header class="page-header" data-reveal><RouterLink class="back" to="/companions"><ArrowLeft :size="16" />返回同行计划</RouterLink><div><p>FIELD / TRAVEL · SHORT ACTIVITY</p><h1>发起短时同行</h1></div></header>
  <form class="activity-grid" @submit.prevent="submit"><section class="form-column" data-reveal><label>活动标题<input v-model="title" maxlength="200" placeholder="例如：西湖日落散步"></label><div class="two"><label>城市代码<input v-model="city" maxlength="32" placeholder="例如：330100"></label><label>活动日期<input v-model="date" type="date"></label></div><div class="two"><label>开始时间<input v-model="startsAt" type="time"></label><label>结束时间<input v-model="endsAt" type="time"></label></div><section class="poi"><header><div><p>VERIFIED PLACE</p><h2>{{ poi?.name || '选择已验证地点' }}</h2><span>{{ poi?.address || '搜索后选择一个地点。' }}</span></div><MapPin :size="20" /></header><div class="poi-search"><input v-model="query" type="search" placeholder="搜索地点" @keyup.enter="search"><button type="button" :disabled="searching" @click="search"><Search :size="15" />{{ searching ? '验证中' : '验证地点' }}</button></div><button v-for="item in results" :key="item.id" class="poi-result" type="button" @click="poi = item; results = []"><strong>{{ item.name }}</strong><span>{{ item.address || item.city }}</span></button></section><label>同行人数<input v-model.number="partySize" type="number" min="2" max="12"></label><div class="three"><label>预算下限<input v-model.number="budgetMin" type="number" min="0" placeholder="可选"></label><label>预算上限<input v-model.number="budgetMax" type="number" min="0" placeholder="可选"></label><label>币种<select v-model="currency"><option>CNY</option><option>USD</option><option>EUR</option></select></label></div><fieldset><legend>活动节奏</legend><label v-for="item in ([['slow', '从容'], ['balanced', '均衡'], ['packed', '紧凑']] as const)" :key="item[0]"><input v-model="pace" type="radio" :value="item[0]">{{ item[1] }}</label></fieldset><fieldset><legend>同行兴趣</legend><label v-for="tag in companionInterestTags" :key="tag"><input type="checkbox" :checked="tags.includes(tag)" @change="toggleTag(tag)">{{ tag }}</label></fieldset><label>同行说明<textarea v-model="intro" rows="5" maxlength="2000" placeholder="介绍这次活动的节奏与期待。"></textarea></label><p class="privacy"><Check :size="16" />仅已加入成员可查看 协作路线与具体集合信息。</p><Transition name="fade"><p v-if="error" class="error-message" role="alert">{{ error }}</p></Transition><button class="submit" type="submit" :disabled="invalid || submitting"><Send :size="16" />{{ submitting ? '正在提交' : '提交活动审核' }}</button></section><aside class="side-note" data-reveal><p>ONE DAY / VERIFIED POI</p><h2>先确定真实地点，再邀请同行。</h2><span>活动会创建一份当天的协作路线。审核通过前不会出现在公开发现页。</span></aside></form></main>
</template>

<style scoped>
/* ============ 页面容器 ============ */
.publish-page {
  color: var(--field-ink);
  margin: 0 auto;
  max-width: 1120px;
  min-height: calc(100vh - 70px);
  padding: 34px 22px 68px;
}

/* ============ 页头 ============ */
.page-header {
  align-items: end;
  border-bottom: 2px solid var(--field-ink);
  display: flex;
  gap: 28px;
  padding-bottom: 22px;
  animation: header-enter var(--motion-slow) var(--ease-out) both;
}

@keyframes header-enter {
  from { opacity: 0; transform: translateY(-10px); }
  to { opacity: 1; transform: translateY(0); }
}

.back {
  align-items: center;
  color: var(--field-teal);
  display: inline-flex;
  font: 800 12px var(--field-mono);
  gap: 6px;
  text-decoration: none;
  transition: color var(--motion-fast) var(--ease-standard), transform var(--motion-fast) var(--ease-standard);
}

.back:hover { color: var(--field-deep); transform: translateX(-2px); }
.back:focus-visible { outline: 3px solid var(--field-saffron); outline-offset: 3px; }

.page-header p, .poi p, .side-note > p {
  color: var(--field-teal);
  font: 800 10px var(--field-mono);
  letter-spacing: .09em;
  margin: 0 0 8px;
}

.page-header h1 { font-size: 36px; letter-spacing: 0; margin: 0; }

/* ============ 布局栅格 ============ */
.activity-grid {
  align-items: start;
  display: grid;
  gap: 54px;
  grid-template-columns: minmax(0, 1fr) 270px;
  padding-top: 31px;
}

.form-column { display: grid; gap: 18px; }

.form-column > label, .two label, .three label {
  color: var(--field-ink-soft);
  display: grid;
  font-size: 12px;
  font-weight: 800;
  gap: 7px;
}

.form-column input, .form-column select, .form-column textarea {
  background: #fff;
  border: 1px solid var(--field-line);
  color: var(--field-ink);
  font: inherit;
  min-height: 42px;
  padding: 9px;
  transition: border-color var(--motion-fast) var(--ease-standard), box-shadow var(--motion-fast) var(--ease-standard);
}

.form-column input:focus-visible, .form-column select:focus-visible, .form-column textarea:focus-visible {
  border-color: var(--field-teal);
  box-shadow: 0 0 0 3px var(--field-teal-soft);
  outline: 0;
}

.form-column textarea { line-height: 1.55; resize: vertical; }

.two, .three { display: grid; gap: 10px; grid-template-columns: 1fr 1fr; }
.three { grid-template-columns: 1fr 1fr 90px; }

/* ============ POI 验证 ============ */
.poi {
  border-bottom: 1px solid var(--field-line);
  border-top: 1px solid var(--field-line);
  display: grid;
  gap: 10px;
  padding: 15px 0;
}

.poi header { align-items: start; display: flex; justify-content: space-between; }
.poi h2 { font-size: 18px; margin: 0; }
.poi span { color: var(--field-muted); font-size: 12px; }
.poi header > svg { color: var(--field-coral); }

.poi-search { display: grid; gap: 8px; grid-template-columns: 1fr auto; }

.poi-search input {
  background: #fff;
  border: 1px solid var(--field-line);
  min-height: 42px;
  padding: 0 10px;
  transition: border-color var(--motion-fast) var(--ease-standard), box-shadow var(--motion-fast) var(--ease-standard);
}

.poi-search input:focus-visible { border-color: var(--field-teal); box-shadow: 0 0 0 3px var(--field-teal-soft); outline: 0; }

.poi-search button, .submit {
  align-items: center;
  background: var(--field-deep);
  border: 0;
  color: #fff;
  cursor: pointer;
  display: inline-flex;
  font-weight: 800;
  gap: 7px;
  justify-content: center;
  padding: 10px 12px;
  transition: background-color var(--motion-base) var(--ease-standard), transform var(--motion-base) var(--ease-standard), box-shadow var(--motion-base) var(--ease-standard);
}

.poi-search button:hover:not(:disabled), .submit:hover:not(:disabled) { background: var(--field-teal); transform: translateY(-1px); box-shadow: var(--shadow-soft); }
.poi-search button:active:not(:disabled), .submit:active:not(:disabled) { transform: translateY(0) scale(0.98); }
.poi-search button:focus-visible, .submit:focus-visible { outline: 3px solid var(--field-saffron); outline-offset: 2px; }
.poi-search button:disabled, .submit:disabled { cursor: not-allowed; opacity: .5; }

.poi-result {
  background: #fff;
  border: 1px solid var(--field-line);
  cursor: pointer;
  display: grid;
  gap: 4px;
  padding: 10px;
  text-align: left;
  transition: border-color var(--motion-fast) var(--ease-standard), background-color var(--motion-fast) var(--ease-standard), transform var(--motion-fast) var(--ease-standard);
}

.poi-result:hover { border-color: var(--field-teal); background: var(--field-teal-soft); transform: translateY(-1px); }
.poi-result:active { transform: scale(0.98); }
.poi-result:focus-visible { outline: 3px solid var(--field-saffron); outline-offset: 2px; }
.poi-result strong { font-size: 13px; }

/* ============ 表单分组 ============ */
fieldset {
  border: 0;
  border-bottom: 1px solid var(--field-line);
  border-top: 1px solid var(--field-line);
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  padding: 14px 0;
}

legend { color: var(--field-ink-soft); font-size: 12px; font-weight: 800; padding: 0 8px 0 0; }
fieldset label { align-items: center; display: flex; font-size: 12px; gap: 5px; }
fieldset input { accent-color: var(--field-teal); min-height: auto !important; padding: 0 !important; }

.privacy {
  align-items: flex-start;
  background: var(--travel-sky);
  color: var(--field-muted);
  display: flex;
  font-size: 12px;
  gap: 8px;
  line-height: 1.5;
  margin: 0;
  padding: 12px;
}

.privacy svg { color: var(--field-teal); flex: 0 0 auto; }

.submit { min-height: 43px; }
.error-message { color: var(--field-coral); font-size: 12px; margin: 0; }

/* ============ 侧边说明 ============ */
.side-note {
  border-top: 2px solid var(--field-ink);
  display: grid;
  gap: 9px;
  padding-top: 16px;
  position: sticky;
  top: 94px;
}

.side-note h2 { font-size: 23px; line-height: 1.25; margin: 0; }
.side-note span { color: var(--field-muted); font-size: 13px; line-height: 1.6; }

/* ============ 响应式 ============ */
@media (max-width: 760px) {
  .publish-page { padding: 22px 15px 42px; }
  .page-header { align-items: start; flex-direction: column; gap: 17px; }
  .activity-grid { grid-template-columns: 1fr; }
  .side-note { position: static; }
  .three { grid-template-columns: 1fr 1fr; }
  .three label:last-child { grid-column: 1 / -1; }
}

@media (prefers-reduced-motion: reduce) {
  .page-header { animation: none; }
  .back, .poi-search button, .submit, .poi-result,
  .form-column input, .form-column select, .form-column textarea, .poi-search input { transition: none; }
}
</style>
