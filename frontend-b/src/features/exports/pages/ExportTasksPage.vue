<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { CircleAlert, Eye, RefreshCw } from 'lucide-vue-next'
import { normalizeApiError } from '@/services/api'
import { listAdminExportTasks, type AdminExportTask, type ExportTaskStatus } from '../services/exportTasks'

const tasks = ref<AdminExportTask[]>([])
const status = ref<ExportTaskStatus | ''>('')
const selected = ref<AdminExportTask>()
const loading = ref(false)
const error = ref('')

const statusOptions: Array<[ExportTaskStatus | '', string]> = [
  ['', '全部状态'], ['queued', '排队'], ['running', '处理中'], ['succeeded', '已完成'], ['failed', '失败'], ['cancelled', '已取消'],
]
const activeCount = computed(() => tasks.value.filter((task) => task.status === 'queued' || task.status === 'running').length)

function statusLabel(value: ExportTaskStatus) { return ({ queued: '排队', running: '处理中', succeeded: '已完成', failed: '失败', cancelled: '已取消' } as Record<ExportTaskStatus, string>)[value] }
function statusType(value: ExportTaskStatus) { return value === 'failed' ? 'danger' : value === 'queued' || value === 'running' ? 'warning' : value === 'cancelled' ? 'info' : 'success' }
function dateTime(value: string | null) { return value ? new Intl.DateTimeFormat('zh-CN', { dateStyle: 'short', timeStyle: 'medium' }).format(new Date(value)) : '未记录' }

async function load() {
  loading.value = true
  error.value = ''
  selected.value = undefined
  try { tasks.value = await listAdminExportTasks(status.value || undefined) } catch (cause) { tasks.value = []; error.value = normalizeApiError(cause).message } finally { loading.value = false }
}

onMounted(load)
</script>

<template>
  <main class="export-tasks-page">
    <section class="page-heading">
      <div><h1>导出任务</h1><p>查看行程文档生成队列和处理结果。此处仅显示运营元数据，不提供下载或重试操作。</p></div>
      <button class="icon-action" type="button" title="刷新任务" :disabled="loading" @click="load"><RefreshCw :size="18" :class="{ spinning: loading }" /></button>
    </section>

    <section class="task-strip" aria-label="导出任务概览"><span>当前列表</span><strong>{{ tasks.length }}</strong><p>处理中 {{ activeCount }} 项</p></section>

    <section class="workbench" aria-label="导出任务列表">
      <div class="filter-row"><el-select v-model="status" aria-label="状态筛选" placeholder="筛选状态" @change="load"><el-option v-for="option in statusOptions" :key="option[0]" :value="option[0]" :label="option[1]" /></el-select><span>{{ loading ? '正在加载任务…' : `共 ${tasks.length} 项` }}</span></div>
      <div v-if="error" class="error-state"><CircleAlert :size="20" /><div><strong>无法加载导出任务</strong><p>{{ error }}</p></div><button type="button" @click="load">重新尝试</button></div>
      <template v-else><el-table :data="tasks" v-loading="loading" row-key="id" highlight-current-row @current-change="selected = $event || undefined"><el-table-column label="任务" min-width="250"><template #default="{ row }"><strong>{{ row.id }}</strong><small>请求人 {{ row.requester_id }}</small></template></el-table-column><el-table-column label="行程版本" min-width="190"><template #default="{ row }"><strong>{{ row.itinerary_id }}</strong><small>版本 {{ row.version_no }} · {{ row.format.toUpperCase() }}</small></template></el-table-column><el-table-column label="进度" width="155"><template #default="{ row }"><el-progress :percentage="row.progress" :status="row.status === 'failed' ? 'exception' : row.status === 'succeeded' ? 'success' : undefined" /></template></el-table-column><el-table-column label="状态" width="120"><template #default="{ row }"><el-tag effect="plain" :type="statusType(row.status)">{{ statusLabel(row.status) }}</el-tag></template></el-table-column><el-table-column label="尝试" width="90"><template #default="{ row }">{{ row.attempt_count }}</template></el-table-column><el-table-column label="更新时间" min-width="170"><template #default="{ row }">{{ dateTime(row.updated_at) }}</template></el-table-column><el-table-column label="操作" width="90" fixed="right"><template #default="{ row }"><button class="text-action" type="button" @click.stop="selected = row"><Eye :size="16" />查看</button></template></el-table-column></el-table><div v-if="!loading && !tasks.length" class="empty-state">当前筛选条件下没有导出任务。</div></template>
    </section>

    <el-drawer :model-value="Boolean(selected)" :with-header="false" size="min(460px, 100%)" @update:model-value="selected = undefined"><div v-if="selected" class="detail"><div class="detail-title"><div><h2>任务详情</h2><span>{{ selected.id }}</span></div><el-tag effect="plain" :type="statusType(selected.status)">{{ statusLabel(selected.status) }}</el-tag></div><dl><dt>行程 ID</dt><dd>{{ selected.itinerary_id }}</dd><dt>行程版本 ID</dt><dd>{{ selected.itinerary_version_id }}</dd><dt>请求人 ID</dt><dd>{{ selected.requester_id }}</dd><dt>进度</dt><dd>{{ selected.progress }}%</dd><dt>尝试次数</dt><dd>{{ selected.attempt_count }}</dd><dt>创建时间</dt><dd>{{ dateTime(selected.created_at) }}</dd><dt>最后尝试</dt><dd>{{ dateTime(selected.last_attempt_at) }}</dd><dt>完成时间</dt><dd>{{ dateTime(selected.finished_at) }}</dd><template v-if="selected.last_error_code || selected.last_error_message"><dt>安全错误信息</dt><dd class="failure">{{ selected.last_error_code || 'EXPORT_FAILED' }}{{ selected.last_error_message ? `: ${selected.last_error_message}` : '' }}</dd></template></dl></div></el-drawer>
  </main>
</template>

<style scoped>
.export-tasks-page{margin:0 auto;max-width:1480px;padding:38px 42px 56px}.page-heading{align-items:flex-start;display:flex;justify-content:space-between;margin-bottom:26px}.page-heading h1{color:#142638;font-size:28px;letter-spacing:0;margin:0 0 8px}.page-heading p{color:#5e6b74;line-height:1.5;margin:0;max-width:720px}.icon-action{align-items:center;background:#fff;border:1px solid #cbd5d9;border-radius:6px;color:#142638;cursor:pointer;display:inline-flex;height:38px;justify-content:center;width:38px}.task-strip{align-items:center;background:#edf3f1;border:1px solid #d7e0df;color:#5e6b74;display:flex;gap:12px;margin-bottom:20px;min-height:58px;padding:0 20px}.task-strip span{font-size:13px}.task-strip strong{color:#142638;font-size:23px}.task-strip p{border-left:1px solid #c9d8d4;margin:0 0 0 6px;padding-left:18px}.workbench{background:#fff;border:1px solid #d7e0df;min-height:320px}.filter-row{align-items:center;border-bottom:1px solid #d7e0df;display:flex;gap:14px;min-height:66px;padding:0 20px}.filter-row span{color:#667680;font-size:13px}.workbench :deep(.el-table){--el-table-header-bg-color:#edf3f1;--el-table-border-color:#d7e0df;--el-table-row-hover-bg-color:#f3f7f5}.workbench :deep(.el-table th.el-table__cell){color:#475762;font-size:12px;font-weight:700}.workbench :deep(.el-table td.el-table__cell){padding:13px 0}.workbench strong{color:#142638;display:block;font-weight:700}.workbench small,.detail-title span{color:#829099;display:block;font-family:ui-monospace,monospace;font-size:11px;margin-top:4px}.text-action{align-items:center;background:none;border:0;color:#167a76;cursor:pointer;display:inline-flex;font-size:13px;gap:4px;padding:4px 0}.icon-action:focus-visible,.text-action:focus-visible{outline:3px solid #d99824;outline-offset:2px}.error-state{align-items:center;background:#fff5f2;color:#9f392b;display:flex;gap:12px;margin:20px;padding:18px}.error-state p{font-size:13px;margin:4px 0 0}.error-state button{background:none;border:0;color:inherit;cursor:pointer;margin-left:auto;text-decoration:underline}.empty-state{color:#64737d;padding:54px;text-align:center}.detail{padding:4px 8px}.detail-title{align-items:flex-start;border-bottom:1px solid #d7e0df;display:flex;justify-content:space-between;padding:8px 0 18px}.detail-title h2{color:#142638;font-size:22px;margin:0}.detail dl{display:grid;grid-template-columns:130px 1fr;margin:22px 0}.detail dt,.detail dd{border-bottom:1px solid #e4eae8;font-size:13px;margin:0;padding:12px 0}.detail dt{color:#71808a}.detail dd{color:#273847;overflow-wrap:anywhere}.failure{color:#b94b3a}.spinning{animation:spin 1s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}@media(max-width:700px){.export-tasks-page{padding:26px 16px 42px}.page-heading{gap:16px}.task-strip{margin-bottom:16px}.detail dl{grid-template-columns:110px 1fr}}
</style>
