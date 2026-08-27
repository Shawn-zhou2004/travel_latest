<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { Check, CircleAlert, Eye, RefreshCw, X } from 'lucide-vue-next'
import { ElMessage } from 'element-plus/es/components/message/index'
import { normalizeApiError } from '@/services/api'
import { listCompanionRequests, listOrders, listPosts, listProviderApplications, listReports, queryOrderPayment, updateCompanionRequest, updatePost, updateProvider, updateReport, type CompanionRequest, type ModerationPost, type ProviderApplication, type Report, type TravelOrder } from '../services/operations'

const props = defineProps<{ area: 'content' | 'companions' | 'reports' | 'providers' | 'orders' }>()
type RecordItem = ModerationPost | CompanionRequest | Report | ProviderApplication | TravelOrder

const records = ref<RecordItem[]>([])
const loading = ref(false)
const error = ref('')
const selected = ref<RecordItem>()
const status = ref('')
const dialogOpen = ref(false)
const decision = ref<'approved' | 'rejected' | 'resolved' | 'dismissed' | 'hidden'>('approved')
const reason = ref('')
const submitting = ref(false)

const title = computed(() => ({ content: '内容审核', companions: '同行计划审核', reports: '举报处理', providers: '供应商审核', orders: '订单查询' }[props.area]))
const description = computed(() => ({
  content: '处理待发布的社区内容，所有决定必须留存理由。',
  companions: '核验同行计划的公开元数据和审核状态，避免风险计划进入公开发现页。',
  reports: '核查用户举报并记录处置结论。',
  providers: '审核入驻主体与资质信息，决定会进入审计记录。',
  orders: '查看订单事实与独立状态；不直接变更支付或履约状态。',
}[props.area]))
const statusOptions = computed(() => props.area === 'orders'
  ? [['', '全部订单'], ['created', '待支付'], ['paid', '已支付'], ['failed', '异常']]
  : [['', '全部状态'], ['pending_review', '待审核'], ['pending', '待处理'], ['approved', '已通过'], ['rejected', '已拒绝'], ['resolved', '已结案']])

function displayStatus(value: string) {
  return ({ pending_review: '待审核', pending: '待处理', approved: '已通过', rejected: '已拒绝', resolved: '已结案', dismissed: '不予处理', hidden: '已隐藏', open: '招募中', full: '已满员', closed: '已关闭', cancelled: '已取消', completed: '已完成', created: '待支付', paying: '支付中', paid: '已支付', failed: '异常', PENDING_CONFIRMATION: '待支付确认', PAYING: '支付中', PAID_PENDING_FULFILLMENT: '已支付，待履约', CONFIRMED: '已完成', FAILED: '订单失败', TICKET_FAILED_AWAITING_REFUND: '出票失败，待退款', REFUNDING: '退款中', REFUNDED: '已退款', CLOSED: '已关闭', pending_confirmation: '待履约确认', confirming: '履约确认中', confirmed: '履约完成', not_supported: '暂不支持履约' } as Record<string, string>)[value] ?? value
}

function reportTargetLabel(value: string) { return ({ post: '社区帖子', comment: '帖子评论' } as Record<string, string>)[value] ?? `未知对象（${value}）` }
function reportReasonLabel(value: string) {
  return ({ spam: '垃圾广告', scam: '诈骗或引流', harassment: '骚扰或辱骂', abusive: '骚扰或辱骂', pornography: '色情低俗', violent: '暴力危险', misinformation: '虚假或误导信息', infringement: '侵权内容', privacy: '泄露隐私', other: '其他原因' } as Record<string, string>)[value] ?? `其他原因（${value}）`
}
function reportStatusLabel(value: string) { return ({ pending: '等待处理', resolved: '已处理', dismissed: '不予处理' } as Record<string, string>)[value] ?? displayStatus(value) }

function contentTypeLabel(value: string) {
  return value === 'itinerary' ? '田野笔记' : value
}

function companionKindLabel(value: CompanionRequest['trip_kind']) {
  return value === 'trip' ? '行程' : value === 'activity' ? '短途活动' : '历史请求'
}

function companionPaceLabel(value: CompanionRequest['travel_pace']) {
  return ({ slow: '慢节奏', balanced: '均衡', packed: '紧凑' } as Record<string, string>)[value ?? ''] ?? '未设置'
}

function recordStatus(record: RecordItem) {
  return 'verification_status' in record ? record.verification_status : record.status
}

async function load() {
  loading.value = true
  error.value = ''
  selected.value = undefined
  try {
    if (props.area === 'content') records.value = await listPosts(status.value || 'pending_review')
    else if (props.area === 'companions') records.value = await listCompanionRequests(status.value || 'pending_review')
    else if (props.area === 'reports') records.value = await listReports(status.value || 'pending')
    else if (props.area === 'providers') records.value = await listProviderApplications(status.value || 'pending_review')
    else records.value = await listOrders(status.value || undefined)
  } catch (cause) {
    records.value = []
    error.value = normalizeApiError(cause).message
  } finally {
    loading.value = false
  }
}

function openDecision(item: RecordItem, next: typeof decision.value) {
  selected.value = item
  decision.value = next
  reason.value = ''
  dialogOpen.value = true
}

async function submitDecision() {
  if (!selected.value || !reason.value.trim()) return
  submitting.value = true
  try {
    if (props.area === 'content') await updatePost(selected.value.id, decision.value === 'approved' ? 'published' : 'rejected', reason.value.trim())
    if (props.area === 'companions') await updateCompanionRequest(selected.value.id, decision.value, reason.value.trim())
    if (props.area === 'reports') await updateReport(selected.value.id, decision.value, reason.value.trim())
    if (props.area === 'providers') await updateProvider(selected.value.id, decision.value, reason.value.trim())
    ElMessage.success('处理结果已提交并进入审计记录。')
    dialogOpen.value = false
    await load()
  } catch (cause) {
    ElMessage.error(normalizeApiError(cause).message)
  } finally {
    submitting.value = false
  }
}

async function refreshPayment(item: TravelOrder) {
  try {
    const order = await queryOrderPayment(item.id)
    records.value = records.value.map((record) => record.id === order.id ? order : record)
    selected.value = order
    ElMessage.success('已获取最新支付状态。')
  } catch (cause) { ElMessage.error(normalizeApiError(cause).message) }
}

watch(() => props.area, () => { status.value = ''; load() })
onMounted(load)
</script>

<template>
  <main class="operations-page">
    <section class="page-heading">
      <div><h1>{{ title }}</h1><p>{{ description }}</p></div>
      <button class="icon-action" type="button" title="刷新队列" :disabled="loading" @click="load"><RefreshCw :size="18" :class="{ spinning: loading }" /></button>
    </section>

    <section class="workbench" aria-label="运营工作台">
      <div class="filter-row"><el-select v-model="status" aria-label="状态筛选" placeholder="筛选状态" @change="load"><el-option v-for="option in statusOptions" :key="option[0]" :value="option[0]" :label="option[1]" /></el-select><span>{{ loading ? '正在加载队列…' : `共 ${records.length} 条记录` }}</span></div>
      <div v-if="error" class="error-state"><CircleAlert :size="20" /><div><strong>无法加载此队列</strong><p>{{ error }}</p></div><button type="button" @click="load">重新尝试</button></div>
      <div v-else class="table-wrap">
        <el-table :data="records" v-loading="loading" row-key="id" highlight-current-row @current-change="selected = $event || undefined">
          <el-table-column label="记录" min-width="230"><template #default="{ row }"><strong>{{ 'title' in row ? row.title : 'legal_name' in row ? row.legal_name : 'order_no' in row ? row.order_no : `${reportTargetLabel(row.target_type)}举报` }}</strong><small>{{ row.id }}</small></template></el-table-column>
          <el-table-column v-if="area === 'content'" label="类型" width="120"><template #default="{ row }">{{ contentTypeLabel(row.content_type) }}</template></el-table-column>
          <el-table-column v-if="area === 'content'" label="路线快照" width="110"><template #default="{ row }">{{ row.has_route_snapshot ? '已附加' : '无' }}</template></el-table-column>
          <el-table-column v-if="area === 'companions'" label="目的地" min-width="130"><template #default="{ row }">{{ row.destination }}</template></el-table-column>
          <el-table-column v-if="area === 'companions'" label="计划类型" width="110"><template #default="{ row }">{{ companionKindLabel(row.trip_kind) }}</template></el-table-column>
          <el-table-column v-if="area === 'companions'" label="日期" min-width="180"><template #default="{ row }">{{ row.start_date && row.end_date ? `${row.start_date} 至 ${row.end_date}` : '历史请求未设置' }}</template></el-table-column>
          <el-table-column v-if="area === 'companions'" label="人数" width="110"><template #default="{ row }">{{ row.party_size ? `${row.accepted_count}/${row.party_size}` : '未设置' }}</template></el-table-column>
          <el-table-column v-if="area === 'companions'" label="节奏" width="100"><template #default="{ row }">{{ companionPaceLabel(row.travel_pace) }}</template></el-table-column>
          <el-table-column v-if="area === 'companions'" label="偏好与介绍" min-width="260"><template #default="{ row }"><span>{{ row.interest_tags.join(' · ') || '未设置标签' }}</span><small>{{ row.intro_text || row.description }}</small></template></el-table-column>
          <el-table-column v-if="area === 'companions'" label="业务状态" width="110"><template #default="{ row }"><el-tag effect="plain" :type="row.business_status === 'completed' || row.business_status === 'cancelled' ? 'info' : row.business_status === 'full' ? 'warning' : 'success'">{{ displayStatus(row.business_status) }}</el-tag></template></el-table-column>
          <el-table-column v-if="area === 'reports'" label="举报对象" width="120"><template #default="{ row }">{{ reportTargetLabel(row.target_type) }}</template></el-table-column>
          <el-table-column v-if="area === 'reports'" label="举报原因" min-width="160"><template #default="{ row }"><strong>{{ reportReasonLabel(row.reason) }}</strong><small v-if="row.details">补充说明：{{ row.details }}</small></template></el-table-column>
          <el-table-column v-if="area === 'providers'" label="主体类型" width="120"><template #default="{ row }">{{ row.provider_type }}</template></el-table-column>
          <el-table-column v-if="area === 'orders'" label="金额" width="125"><template #default="{ row }">{{ row.currency }} {{ row.amount }}</template></el-table-column>
          <el-table-column v-if="area === 'orders'" label="支付状态" width="130"><template #default="{ row }"><el-tag effect="plain" :type="row.payment_status === 'failed' ? 'danger' : row.payment_status === 'paid' ? 'success' : 'warning'">{{ displayStatus(row.payment_status) }}</el-tag></template></el-table-column>
          <el-table-column v-if="area === 'orders'" label="履约状态" width="140"><template #default="{ row }"><el-tag effect="plain" :type="row.fulfillment_status === 'failed' ? 'danger' : row.fulfillment_status === 'confirmed' ? 'success' : 'warning'">{{ displayStatus(row.fulfillment_status) }}</el-tag></template></el-table-column>
          <el-table-column :label="area === 'reports' ? '处理状态' : area === 'orders' ? '订单状态' : '状态'" width="150"><template #default="{ row }"><el-tag effect="plain" :type="recordStatus(row).includes('reject') || recordStatus(row) === 'failed' ? 'danger' : recordStatus(row).includes('pending') || recordStatus(row) === 'created' ? 'warning' : 'success'">{{ area === 'reports' ? reportStatusLabel(recordStatus(row)) : displayStatus(recordStatus(row)) }}</el-tag></template></el-table-column>
          <el-table-column label="操作" width="210" fixed="right"><template #default="{ row }"><button class="text-action" type="button" @click.stop="selected = row"><Eye :size="16" />查看</button><template v-if="area !== 'orders'"><button class="text-action success" type="button" @click.stop="openDecision(row, area === 'reports' ? 'resolved' : 'approved')"><Check :size="16" />{{ area === 'reports' ? '结案' : '通过' }}</button><button class="text-action danger" type="button" @click.stop="openDecision(row, area === 'reports' ? 'dismissed' : 'rejected')"><X :size="16" />{{ area === 'reports' ? '忽略' : '拒绝' }}</button></template><button v-else class="text-action" type="button" @click.stop="refreshPayment(row)">查询支付</button></template></el-table-column>
        </el-table>
        <div v-if="!loading && !records.length" class="empty-state">当前筛选条件下没有待处理记录。</div>
      </div>
    </section>

    <el-drawer :model-value="Boolean(selected)" :with-header="false" size="min(460px, 100%)" @update:model-value="selected = undefined"><div v-if="selected" class="detail"><div class="detail-title"><div><h2>记录详情</h2><span>{{ selected.id }}</span></div><el-tag effect="plain">{{ area === 'reports' ? reportStatusLabel(recordStatus(selected)) : displayStatus(recordStatus(selected)) }}</el-tag></div><dl v-if="area === 'reports'" class="report-detail"><dt>举报对象</dt><dd>{{ reportTargetLabel((selected as Report).target_type) }}</dd><dt>举报原因</dt><dd>{{ reportReasonLabel((selected as Report).reason) }}</dd><dt>补充说明</dt><dd>{{ (selected as Report).details || '举报人未补充说明。' }}</dd><dt>处理结论</dt><dd>{{ (selected as Report).resolution || '尚未处理。' }}</dd><dt>举报时间</dt><dd>{{ (selected as Report).created_at }}</dd></dl><dl v-else><template v-for="(value, key) in selected" :key="String(key)"><dt v-if="value !== null && value !== undefined">{{ String(key).replace(/_/g, ' ') }}</dt><dd v-if="value !== null && value !== undefined">{{ typeof value === 'object' ? JSON.stringify(value) : value }}</dd></template></dl><div v-if="area !== 'orders'" class="detail-actions"><button type="button" class="secondary-button" @click="openDecision(selected, area === 'reports' ? 'dismissed' : 'rejected')">{{ area === 'reports' ? '不予处理' : '拒绝' }}</button><button type="button" class="primary-button" @click="openDecision(selected, area === 'reports' ? 'resolved' : 'approved')">{{ area === 'reports' ? '确认处理' : '通过' }}</button></div><button v-else type="button" class="primary-button full" @click="refreshPayment(selected as TravelOrder)">向支付渠道查询最新状态</button></div></el-drawer>

    <el-dialog v-model="dialogOpen" width="min(440px, calc(100% - 32px))" :title="decision === 'approved' || decision === 'resolved' ? '确认处理' : '确认拒绝'" destroy-on-close><p class="dialog-copy">请记录处理依据。该说明将与本次操作一同进入审计记录。</p><el-input v-model="reason" type="textarea" :rows="4" maxlength="500" show-word-limit placeholder="填写清晰、可复核的处理依据" /><template #footer><button type="button" class="secondary-button" @click="dialogOpen = false">取消</button><button type="button" class="primary-button" :disabled="!reason.trim() || submitting" @click="submitDecision">{{ submitting ? '提交中…' : '确认提交' }}</button></template></el-dialog>
  </main>
</template>

<style scoped>
.operations-page{margin:0 auto;max-width:1480px;padding:38px 42px 56px}.page-heading{align-items:flex-start;display:flex;justify-content:space-between;margin-bottom:28px}.page-heading h1{color:#142638;font-size:28px;letter-spacing:0;margin:0 0 8px}.page-heading p{color:#5e6b74;margin:0}.icon-action{align-items:center;background:#fff;border:1px solid #cbd5d9;border-radius:6px;color:#142638;cursor:pointer;display:inline-flex;height:38px;justify-content:center;width:38px}.icon-action:focus-visible,.text-action:focus-visible,.primary-button:focus-visible,.secondary-button:focus-visible{outline:3px solid #d99824;outline-offset:2px}.workbench{background:#fff;border:1px solid #d7e0df}.filter-row{align-items:center;border-bottom:1px solid #d7e0df;display:flex;gap:14px;min-height:66px;padding:0 20px}.filter-row span{color:#667680;font-size:13px}.table-wrap{min-height:300px}.table-wrap :deep(.el-table){--el-table-header-bg-color:#edf3f1;--el-table-border-color:#d7e0df;--el-table-row-hover-bg-color:#f3f7f5}.table-wrap :deep(.el-table th.el-table__cell){color:#475762;font-size:12px;font-weight:700}.table-wrap :deep(.el-table td.el-table__cell){padding:13px 0}.table-wrap strong{color:#142638;display:block;font-weight:700}.table-wrap small{color:#829099;display:block;font-family:ui-monospace,monospace;font-size:11px;margin-top:4px}.text-action{align-items:center;background:none;border:0;color:#167a76;cursor:pointer;display:inline-flex;font-size:13px;gap:4px;margin-right:10px;padding:4px 0}.text-action.danger{color:#b94b3a}.text-action.success{color:#167a76}.error-state{align-items:center;background:#fff5f2;color:#9f392b;display:flex;gap:12px;margin:20px;padding:18px}.error-state p{font-size:13px;margin:4px 0 0}.error-state button{background:none;border:0;color:inherit;cursor:pointer;margin-left:auto;text-decoration:underline}.empty-state{color:#64737d;padding:54px;text-align:center}.detail{padding:4px 8px}.detail-title{align-items:flex-start;border-bottom:1px solid #d7e0df;display:flex;justify-content:space-between;padding-bottom:18px}.detail h2{color:#142638;font-size:20px;margin:0 0 5px}.detail-title span{color:#7b8991;font-family:ui-monospace,monospace;font-size:11px}.detail dl{display:grid;gap:6px;margin:24px 0}.detail dt{color:#74828a;font-size:12px;text-transform:capitalize}.detail dd{color:#243843;line-height:1.55;margin:0 0 11px;overflow-wrap:anywhere}.detail-actions{display:flex;gap:10px}.primary-button,.secondary-button{border-radius:5px;cursor:pointer;font-size:14px;font-weight:700;padding:10px 15px}.primary-button{background:#167a76;border:1px solid #167a76;color:#fff}.primary-button:disabled{cursor:not-allowed;opacity:.55}.secondary-button{background:#fff;border:1px solid #b9c6c8;color:#263943}.full{margin-top:4px;width:100%}.dialog-copy{color:#5e6b74;line-height:1.6;margin:0 0 16px}.spinning{animation:spin .8s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}@media(max-width:720px){.operations-page{padding:24px 16px}.page-heading h1{font-size:24px}.filter-row{padding:12px 14px}.table-wrap :deep(.el-table__fixed-right){display:none}.text-action{margin-right:7px}.detail-actions{flex-direction:column}.detail-actions button{width:100%}}
</style>
