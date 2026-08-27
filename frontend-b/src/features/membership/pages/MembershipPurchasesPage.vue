<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { CircleAlert, RefreshCw, RotateCw } from 'lucide-vue-next'
import { ElMessage, ElMessageBox } from 'element-plus'
import { normalizeApiError } from '@/services/api'
import { listMembershipPurchases, retryMembershipPurchaseAuthorization, type AdminMembershipPurchase, type MembershipPurchaseStatus } from '../services/membershipPurchases'

const purchases = ref<AdminMembershipPurchase[]>([])
const status = ref<MembershipPurchaseStatus | ''>('')
const loading = ref(false)
const retryingId = ref('')
const error = ref('')
const statusOptions: Array<[MembershipPurchaseStatus | '', string]> = [['', '全部订单'], ['pending_payment', '待支付'], ['paid', '已支付'], ['closed', '已关闭']]

function dateTime(value: string | null) {
  return value ? new Intl.DateTimeFormat('zh-CN', { dateStyle: 'short', timeStyle: 'short' }).format(new Date(value)) : '未确认'
}

function paymentLabel(value: AdminMembershipPurchase['payment_status']) {
  return ({ pending: '待支付', paying: '支付中', paid: '已支付', failed: '支付失败' })[value]
}

function authorizationLabel(value: AdminMembershipPurchase['authorization_status']) {
  return ({ pending: '待授权', authorized: '已授权', failed: '授权失败' })[value]
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    purchases.value = await listMembershipPurchases(status.value || undefined)
  } catch (cause) {
    purchases.value = []
    error.value = normalizeApiError(cause).message
  } finally {
    loading.value = false
  }
}

async function retryAuthorization(purchase: AdminMembershipPurchase) {
  try {
    await ElMessageBox.confirm('仅会对已支付且尚未授权的订单重新执行权益开通，不会创建新的支付或订单。', '确认重试授权', { confirmButtonText: '重试授权', cancelButtonText: '取消', type: 'warning' })
  } catch {
    return
  }
  retryingId.value = purchase.id
  try {
    await retryMembershipPurchaseAuthorization(purchase.id)
    ElMessage.success('权益授权已重新执行。')
    await load()
  } catch (cause) {
    ElMessage.error(normalizeApiError(cause).message)
  } finally {
    retryingId.value = ''
  }
}

onMounted(load)
</script>

<template>
  <main class="purchase-page">
    <section class="page-heading"><div><h1>会员购买审计</h1><p>查看服务端确认的订单、支付和权益状态。此页不展示回调内容、签名或其他敏感支付数据。</p></div><button class="icon-action" type="button" title="刷新购买记录" :disabled="loading" @click="load"><RefreshCw :size="18" :class="{ spinning: loading }" /></button></section>
    <section class="workbench"><div class="filter-row"><el-select v-model="status" aria-label="购买状态筛选" @change="load"><el-option v-for="option in statusOptions" :key="option[0]" :value="option[0]" :label="option[1]" /></el-select><span>{{ loading ? '正在加载购买记录…' : `共 ${purchases.length} 笔` }}</span></div><div v-if="error" class="error-state"><CircleAlert :size="20" /><div><strong>无法加载购买记录</strong><p>{{ error }}</p></div><button type="button" @click="load">重新尝试</button></div><template v-else><el-table :data="purchases" v-loading="loading" row-key="id"><el-table-column label="用户 / 计划" min-width="230"><template #default="{ row }"><strong>{{ row.plan_name }}</strong><small>{{ row.user_id }}</small></template></el-table-column><el-table-column label="金额 / 权益" min-width="160"><template #default="{ row }">{{ row.amount }} {{ row.currency }}<small>{{ row.duration_days }} 天 · {{ row.generation_quota }} 次生成 · {{ row.assistant_quota }} 次对话</small></template></el-table-column><el-table-column label="支付状态" width="110"><template #default="{ row }"><el-tag effect="plain" :type="row.payment_status === 'paid' ? 'success' : row.payment_status === 'failed' ? 'danger' : 'warning'">{{ paymentLabel(row.payment_status) }}</el-tag></template></el-table-column><el-table-column label="授权状态" width="110"><template #default="{ row }"><el-tag effect="plain" :type="row.authorization_status === 'authorized' ? 'success' : row.authorization_status === 'failed' ? 'danger' : 'warning'">{{ authorizationLabel(row.authorization_status) }}</el-tag></template></el-table-column><el-table-column label="有效期" min-width="170"><template #default="{ row }"><div>{{ dateTime(row.valid_from) }}</div><small>至 {{ dateTime(row.valid_until) }}</small></template></el-table-column><el-table-column label="异常 / 时间" min-width="170"><template #default="{ row }"><div>{{ row.failure_code || '无异常' }}</div><small>创建于 {{ dateTime(row.created_at) }}</small></template></el-table-column><el-table-column label="操作" width="120" fixed="right"><template #default="{ row }"><button v-if="row.payment_status === 'paid' && row.authorization_status !== 'authorized'" class="text-action" type="button" :disabled="retryingId === row.id" @click="retryAuthorization(row)"><RotateCw :size="16" />{{ retryingId === row.id ? '处理中' : '重试授权' }}</button><span v-else class="muted">无需操作</span></template></el-table-column></el-table><div v-if="!loading && !purchases.length" class="empty-state">当前筛选条件下没有购买记录。</div></template></section>
  </main>
</template>

<style scoped>
.purchase-page{margin:0 auto;max-width:1480px;padding:38px 42px 56px}.page-heading{align-items:flex-start;display:flex;gap:24px;justify-content:space-between;margin-bottom:24px}.page-heading h1{color:#142638;font-size:28px;letter-spacing:0;margin:0 0 8px}.page-heading p{color:#5e6b74;line-height:1.5;margin:0;max-width:760px}.icon-action{align-items:center;background:#fff;border:1px solid #cbd5d9;border-radius:6px;color:#142638;cursor:pointer;display:inline-flex;height:38px;justify-content:center;width:38px}.icon-action:disabled,.text-action:disabled{cursor:not-allowed;opacity:.55}.workbench{background:#fff;border:1px solid #d7e0df;min-height:320px}.filter-row{align-items:center;border-bottom:1px solid #d7e0df;display:flex;gap:14px;min-height:66px;padding:0 20px}.filter-row span{color:#667680;font-size:13px}.workbench :deep(.el-table){--el-table-header-bg-color:#edf3f1;--el-table-border-color:#d7e0df;--el-table-row-hover-bg-color:#f3f7f5}.workbench :deep(.el-table th.el-table__cell){color:#475762;font-size:12px;font-weight:700}.workbench :deep(.el-table td.el-table__cell){padding:13px 0}.workbench strong{color:#142638;display:block;font-weight:700}.workbench small{color:#829099;display:block;font-family:ui-monospace,monospace;font-size:11px;margin-top:4px;overflow-wrap:anywhere}.text-action{align-items:center;background:none;border:0;color:#167a76;cursor:pointer;display:inline-flex;font-size:13px;gap:4px;padding:4px 0}.muted{color:#829099;font-size:13px}.error-state{align-items:center;background:#fff5f2;color:#9f392b;display:flex;gap:12px;margin:20px;padding:18px}.error-state p{font-size:13px;margin:4px 0 0}.error-state button{background:none;border:0;color:inherit;cursor:pointer;margin-left:auto;text-decoration:underline}.empty-state{color:#64737d;padding:54px;text-align:center}.icon-action:focus-visible,.text-action:focus-visible,.error-state button:focus-visible{outline:3px solid #d99824;outline-offset:2px}.spinning{animation:spin .8s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}@media(max-width:760px){.purchase-page{padding:26px 16px 40px}.page-heading{align-items:stretch;flex-direction:column}.icon-action{align-self:flex-end}.filter-row{padding:12px 16px}}
</style>
