<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { Check, CircleAlert, RefreshCw, X } from 'lucide-vue-next'
import { ElMessage } from 'element-plus/es/components/message/index'
import { normalizeApiError } from '@/services/api'
import { decidePoiCandidate, listPoiCandidates, poiCandidateTags, type PoiCandidate, type PoiCandidateStatus, type PoiCandidateTag } from '../services/poiCandidates'

const status = ref<PoiCandidateStatus>('pending_review')
const cityCode = ref('')
const candidates = ref<PoiCandidate[]>([])
const loading = ref(false)
const error = ref('')
const selected = ref<PoiCandidate | null>(null)
const dialogOpen = ref(false)
const decision = ref<'approved' | 'rejected' | 'retired'>('approved')
const tags = ref<PoiCandidateTag[]>([])
const weight = ref(0)
const reason = ref('')

async function load() {
  loading.value = true; error.value = ''
  try { candidates.value = await listPoiCandidates(status.value, cityCode.value.trim() || undefined) }
  catch (cause) { error.value = normalizeApiError(cause).message }
  finally { loading.value = false }
}
function open(item: PoiCandidate, next: 'approved' | 'rejected' | 'retired') {
  selected.value = item; decision.value = next; tags.value = [...item.tags]; weight.value = item.admin_weight; reason.value = ''; dialogOpen.value = true
}
function toggleTag(tag: PoiCandidateTag) {
  tags.value = tags.value.includes(tag) ? tags.value.filter((item) => item !== tag) : [...tags.value, tag]
}
async function submit() {
  const item = selected.value
  if (!item || (decision.value === 'approved' && !tags.value.length) || (decision.value !== 'approved' && !reason.value.trim())) return
  try {
    await decidePoiCandidate(item.id, { status: decision.value, tags: decision.value === 'approved' ? tags.value : undefined, admin_weight: decision.value === 'approved' ? weight.value : undefined, reason: reason.value.trim() || undefined })
    dialogOpen.value = false; ElMessage.success(decision.value === 'approved' ? '景点已通过审核，等待官方资料索引复核。' : '候选景点状态已更新。'); await load()
  } catch (cause) { ElMessage.error(normalizeApiError(cause).message) }
}
onMounted(load)
</script>

<template>
  <main class="page"><header><div><h1>景点候选审核</h1><p>仅用户确认采用的高德验证景点会进入这里。通过后才能参与推荐，仍需在 AI 运营中审核并索引官方资料。</p></div><button class="icon" type="button" title="刷新" :disabled="loading" @click="load"><RefreshCw :size="18" :class="{ spin: loading }" /></button></header>
    <section class="filters"><el-select v-model="status" aria-label="候选状态" @change="load"><el-option value="pending_review" label="待审核" /><el-option value="approved" label="已批准" /><el-option value="rejected" label="已拒绝" /><el-option value="retired" label="已退役" /></el-select><el-input v-model="cityCode" maxlength="32" placeholder="城市代码，例如 460200" @keyup.enter="load" /><button type="button" @click="load">筛选</button></section>
    <p v-if="error" class="error"><CircleAlert :size="18" />{{ error }}</p>
    <el-table :data="candidates" v-loading="loading" row-key="id"><el-table-column label="景点" min-width="230"><template #default="{ row }"><strong>{{ row.name }}</strong><small>{{ row.city_code }} · {{ row.amap_type || '未分类' }}</small></template></el-table-column><el-table-column label="内部热度" width="180"><template #default="{ row }"><span>权重 {{ row.admin_weight }}</span><small>采用 {{ row.confirmed_itinerary_count }} · 发现 {{ row.discovery_count }}</small></template></el-table-column><el-table-column label="标签" min-width="210"><template #default="{ row }"><el-tag v-for="tag in row.tags" :key="tag" effect="plain">{{ tag }}</el-tag><span v-if="!row.tags.length">待标注</span></template></el-table-column><el-table-column label="状态" width="110"><template #default="{ row }">{{ row.status }}</template></el-table-column><el-table-column label="操作" width="220" fixed="right"><template #default="{ row }"><button v-if="row.status === 'pending_review'" type="button" class="action" @click="open(row, 'approved')"><Check :size="16" />通过</button><button v-if="row.status === 'pending_review'" type="button" class="action danger" @click="open(row, 'rejected')"><X :size="16" />拒绝</button><button v-if="row.status === 'approved'" type="button" class="action danger" @click="open(row, 'retired')">退役</button></template></el-table-column></el-table>
    <p v-if="!loading && !candidates.length" class="empty">当前筛选条件下没有候选景点。</p>
    <el-dialog v-model="dialogOpen" width="min(580px, calc(100% - 32px))" :title="decision === 'approved' ? '通过景点候选' : decision === 'rejected' ? '拒绝景点候选' : '退役景点候选'" destroy-on-close><form @submit.prevent="submit"><p class="name">{{ selected?.name }}</p><template v-if="decision === 'approved'"><div class="tags"><button v-for="tag in poiCandidateTags" :key="tag" type="button" :class="{ chosen: tags.includes(tag) }" @click="toggleTag(tag)">{{ tag }}</button></div><label>推荐权重<el-input-number v-model="weight" :min="0" :max="100" /></label></template><el-input v-model="reason" type="textarea" :rows="4" maxlength="500" :placeholder="decision === 'approved' ? '可选：填写审核依据' : '必须填写处理原因'" /><div class="buttons"><button type="button" @click="dialogOpen = false">取消</button><button type="submit" :disabled="(decision === 'approved' && !tags.length) || (decision !== 'approved' && !reason.trim())">确认</button></div></form></el-dialog>
  </main>
</template>

<style scoped>
.page{margin:0 auto;max-width:1380px;padding:38px 42px 56px}.page header{align-items:flex-start;display:flex;justify-content:space-between;margin-bottom:22px}.page h1{color:#142638;font-size:28px;margin:0 0 8px}.page header p{color:#5e6b74;line-height:1.55;margin:0;max-width:740px}.icon,.filters button,.action,.buttons button,.tags button{background:#fff;border:1px solid #cbd5d9;border-radius:6px;color:#142638;cursor:pointer;font:inherit;padding:8px 11px}.icon{display:grid;place-items:center}.filters{display:flex;gap:10px;margin-bottom:18px}.filters :deep(.el-select),.filters :deep(.el-input){max-width:220px}.error{align-items:center;background:#fbe7e2;color:#9f392b;display:flex;gap:8px;padding:12px}.action{align-items:center;display:inline-flex;gap:5px;margin-right:8px}.danger{color:#a63d2e}.page :deep(.el-table){--el-table-header-bg-color:#edf3f1}.page small{color:#667680;display:block;font-size:11px;margin-top:4px}.page :deep(.el-tag){margin:2px 4px 2px 0}.empty{color:#667680;padding:32px;text-align:center}.name{font-weight:700}.tags{display:flex;flex-wrap:wrap;gap:8px;margin:14px 0}.tags button.chosen{background:#167a76;border-color:#167a76;color:#fff}.buttons{display:flex;gap:10px;justify-content:flex-end;margin-top:16px}.buttons button:last-child{background:#167a76;border-color:#167a76;color:#fff}.spin{animation:spin 1s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}@media(max-width:760px){.page{padding:24px 16px 40px}.filters{flex-wrap:wrap}.filters :deep(.el-select),.filters :deep(.el-input){max-width:none;width:100%}}
</style>
