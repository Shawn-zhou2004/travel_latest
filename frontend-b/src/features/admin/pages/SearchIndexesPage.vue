<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { CircleAlert, Database, RefreshCw, RotateCw } from 'lucide-vue-next'
import { normalizeApiError } from '@/services/api'
import { getSearchIndexRebuildJob, listSearchIndexes, rebuildSearchIndex, type SearchIndexInventoryItem, type SearchIndexRebuildJob } from '../services/searchIndexes'

const items = ref<SearchIndexInventoryItem[]>([])
const loading = ref(false)
const error = ref('')
const rebuildJobs = ref<Record<string, SearchIndexRebuildJob>>({})
let pollTimer: ReturnType<typeof setTimeout> | undefined
let isUnmounted = false

const labels: Record<string, string> = { travel_knowledge: '旅行知识', official_knowledge: '官方知识', community_knowledge: '社区知识', user_memory: '用户记忆' }
const descriptions: Record<string, string> = {
  official_knowledge: '已审核的 POI、旅行规则和城市模板，供 AI 行程规划与事实问答检索。',
  community_knowledge: '审核通过的公开社区攻略与体验，用于补充旅行灵感和经验。',
  travel_knowledge: '历史共享知识索引，仅用于兼容旧数据，新的官方与社区资料已按知识域拆分。',
  user_memory: '用户私有偏好检索投影，仅当前用户可读取，管理端不能查看或重建。',
}
const statusLabels: Record<SearchIndexInventoryItem['status'], string> = { healthy: '健康', empty: '空索引', unavailable: '不可用', degraded: '降级' }

function statusType(status: SearchIndexInventoryItem['status']) { return status === 'healthy' ? 'success' : status === 'empty' ? 'info' : status === 'degraded' ? 'warning' : 'danger' }
function canRebuild(logicalName: string) { return logicalName === 'official_knowledge' || logicalName === 'community_knowledge' }
function jobLabel(job: SearchIndexRebuildJob) { return job.status === 'queued' ? '重建排队中' : job.status === 'running' ? `重建中 ${job.progress}%` : job.status === 'succeeded' ? '重建完成' : '重建失败' }
function stopPolling() { if (pollTimer) { clearTimeout(pollTimer); pollTimer = undefined } }
function schedulePolling() { stopPolling(); if (!isUnmounted && Object.values(rebuildJobs.value).some((job) => job.status === 'queued' || job.status === 'running')) pollTimer = setTimeout(pollJobs, 1500) }
async function pollJobs() {
  const activeJobs = Object.values(rebuildJobs.value).filter((job) => job.status === 'queued' || job.status === 'running')
  if (!activeJobs.length) return
  try {
    const jobs = await Promise.all(activeJobs.map((job) => getSearchIndexRebuildJob(job.id)))
    for (const job of jobs) rebuildJobs.value[job.index_name] = job
    if (jobs.some((job) => job.status === 'succeeded')) await load()
  } catch (cause) {
    for (const job of activeJobs) rebuildJobs.value[job.index_name] = { ...job, status: 'failed', error: normalizeApiError(cause).message }
  } finally { schedulePolling() }
}
async function load() {
  loading.value = true
  error.value = ''
  try { items.value = await listSearchIndexes() } catch (cause) { items.value = []; error.value = normalizeApiError(cause).message } finally { loading.value = false }
}
async function rebuild(item: SearchIndexInventoryItem) {
  try { rebuildJobs.value[item.logical_name] = await rebuildSearchIndex(item.logical_name); schedulePolling() } catch (cause) { rebuildJobs.value[item.logical_name] = { id: '', index_name: item.logical_name, requested_by: '', status: 'failed', progress: 0, error: normalizeApiError(cause).message, created_at: '', updated_at: '', started_at: null, completed_at: null } }
}
onMounted(load)
onUnmounted(() => { isUnmounted = true; stopPolling() })
</script>

<template>
  <main class="search-page">
    <header class="page-heading">
      <div><p class="eyebrow">检索数据维护</p><h1>搜索索引</h1><p>这是知识资料的检索加速副本，不是业务数据原件。资料审核通过后会写入索引，供关键词和语义检索使用。</p></div>
      <button class="icon-action" type="button" title="刷新索引状态" :disabled="loading" @click="load"><RefreshCw :size="18" :class="{ spinning: loading }" /></button>
    </header>
    <div v-if="error" class="error-state" role="alert">
      <CircleAlert :size="20" /><div><strong>无法加载搜索索引</strong><p>{{ error }}</p></div><button type="button" @click="load">重新尝试</button>
    </div>
    <div v-else-if="!loading && !items.length" class="empty-state"><Database :size="28" /><strong>暂无已配置索引</strong><p>后端尚未配置可供管理的搜索索引。</p></div>
    <div v-else class="index-grid" v-loading="loading" aria-label="搜索索引清单">
      <article v-for="item in items" :key="item.logical_name" class="index-row">
        <div class="index-icon"><Database :size="20" /></div>
        <div class="index-info"><strong>{{ labels[item.logical_name] ?? item.logical_name }}</strong><span>{{ descriptions[item.logical_name] ?? '用于平台检索能力的索引数据。' }}</span><code>{{ item.index_name }}</code></div>
        <div class="index-count"><span>文档数</span><strong>{{ item.document_count === null ? '未获取' : item.document_count.toLocaleString() }}</strong></div>
        <span class="status-tag" :class="`status-${statusType(item.status)}`">{{ statusLabels[item.status] }}</span>
        <div v-if="canRebuild(item.logical_name)" class="rebuild-control">
          <button class="rebuild-button" type="button" :disabled="rebuildJobs[item.logical_name]?.status === 'queued' || rebuildJobs[item.logical_name]?.status === 'running'" @click="rebuild(item)"><RotateCw :size="15" :class="{ spinning: rebuildJobs[item.logical_name]?.status === 'running' }" />从已审核资料重新建立</button>
          <span v-if="rebuildJobs[item.logical_name]" class="rebuild-status" :class="`rebuild-${rebuildJobs[item.logical_name].status}`">{{ jobLabel(rebuildJobs[item.logical_name]) }}<template v-if="rebuildJobs[item.logical_name].error">：{{ rebuildJobs[item.logical_name].error }}</template></span>
        </div>
        <p v-if="item.message" class="item-message">{{ item.message }}</p>
      </article>
    </div>
  </main>
</template>

<style scoped>
.search-page{margin:0 auto;max-width:1180px;padding:38px 42px 56px}.page-heading{align-items:flex-start;display:flex;justify-content:space-between;margin-bottom:28px}.page-heading h1{color:#142638;font-size:28px;letter-spacing:0;margin:0 0 8px}.page-heading p{color:#5e6b74;margin:0}.eyebrow{color:#167a76!important;font-size:11px!important;font-weight:800;letter-spacing:1.4px;margin:0 0 8px!important}.icon-action{align-items:center;background:#fff;border:1px solid #cbd5d9;border-radius:6px;color:#142638;cursor:pointer;display:inline-flex;height:38px;justify-content:center;width:38px}.icon-action:focus-visible,.error-state button:focus-visible{outline:3px solid #d99824;outline-offset:2px}.index-grid{background:#fff;border:1px solid #d7e0df}.index-row{align-items:center;border-bottom:1px solid #e3eae8;display:grid;gap:18px;grid-template-columns:40px minmax(0,1fr) 100px 90px;padding:20px}.index-row:last-child{border-bottom:0}.index-icon{align-items:center;background:#e8f2ef;color:#167a76;display:flex;height:40px;justify-content:center;width:40px}.index-info strong,.index-info code{display:block}.index-info strong{color:#142638;font-size:16px}.index-info code{color:#829099;font-size:12px;margin-top:6px}.index-count span{color:#829099;display:block;font-size:12px}.index-count strong{color:#142638;display:block;font-size:16px;margin-top:4px}.item-message{color:#9f392b;font-size:12px;grid-column:2 / -1;margin:0}.error-state{align-items:center;background:#fff5f2;color:#9f392b;display:flex;gap:12px;padding:18px}.error-state p{font-size:13px;margin:4px 0 0}.error-state button{background:none;border:0;color:inherit;cursor:pointer;margin-left:auto;text-decoration:underline}.empty-state{align-items:center;background:#fff;border:1px solid #d7e0df;color:#64737d;display:flex;flex-direction:column;gap:10px;padding:64px;text-align:center}.empty-state strong{color:#142638}.empty-state p{margin:0}@media(max-width:640px){.search-page{padding:28px 16px 44px}.index-row{grid-template-columns:40px minmax(0,1fr) auto;gap:12px;padding:16px}.index-count{grid-column:2}.index-row :deep(.el-tag){grid-column:3;grid-row:1}.item-message{grid-column:1 / -1}}
 .status-tag{border:1px solid;border-radius:999px;display:inline-block;font-size:12px;padding:4px 8px;text-align:center}.status-success{background:#edf8f1;border-color:#a8d9b7;color:#24743d}.status-info{background:#f1f4f5;border-color:#cbd5d9;color:#64737d}.status-warning{background:#fff8e9;border-color:#e8c878;color:#946b12}.status-danger{background:#fff1ee;border-color:#e6b2a8;color:#9f392b}.rebuild-control{align-items:flex-start;display:flex;flex-direction:column;gap:6px;grid-column:2 / -1}.rebuild-button{align-items:center;background:#fff;border:1px solid #cbd5d9;border-radius:6px;color:#142638;cursor:pointer;display:inline-flex;font-size:12px;font-weight:700;gap:6px;min-height:30px;padding:0 9px}.rebuild-button:disabled{cursor:wait;opacity:.65}.rebuild-button:focus-visible{outline:3px solid #d99824;outline-offset:2px}.rebuild-status{color:#64737d;font-size:12px;line-height:1.4}.rebuild-succeeded{color:#24743d}.rebuild-failed{color:#9f392b}
</style>
