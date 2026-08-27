<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Archive, CircleAlert, Pencil, Plus, RefreshCw, Send } from 'lucide-vue-next'
import { ElMessage } from 'element-plus/es/components/message/index'
import { normalizeApiError } from '@/services/api'
import { archiveMembershipPlan, createMembershipPlan, listMembershipPlans, publishMembershipPlan, updateMembershipPlan, type MembershipPlan, type MembershipPlanStatus } from '../services/membershipPlans'

const plans = ref<MembershipPlan[]>([])
const status = ref<MembershipPlanStatus | ''>('')
const loading = ref(false)
const error = ref('')
const createOpen = ref(false)
const editOpen = ref(false)
const submitting = ref(false)
const actionId = ref('')
const form = ref({ code: '', name: '', durationDays: 30, entitlements: '', priceAmount: 19.9, generationQuota: 10, assistantQuota: 300 })
const editForm = ref({ id: '', durationDays: 30, priceAmount: 19.9, generationQuota: 10, assistantQuota: 300, purchasable: false })

const statusOptions: Array<[MembershipPlanStatus | '', string]> = [
  ['', '全部状态'], ['draft', '草稿'], ['published', '已发布'], ['archived', '已归档'],
]
const publishedCount = computed(() => plans.value.filter((plan) => plan.status === 'published').length)
const canSubmit = computed(() => /^[a-z0-9][a-z0-9_-]*$/.test(form.value.code.trim())
  && form.value.name.trim().length > 0
  && form.value.durationDays >= 1
  && form.value.durationDays <= 3650
  && form.value.priceAmount > 0
  && form.value.generationQuota >= 0
  && form.value.generationQuota <= 10000
  && form.value.assistantQuota >= 0
  && form.value.assistantQuota <= 1000000
  && entitlementCodes().length > 0)
const canUpdate = computed(() => editForm.value.durationDays >= 1
  && editForm.value.durationDays <= 3650
  && editForm.value.priceAmount > 0
  && editForm.value.generationQuota >= 0
  && editForm.value.generationQuota <= 10000
  && editForm.value.assistantQuota >= 0
  && editForm.value.assistantQuota <= 1000000)

function entitlementCodes() {
  return [...new Set(form.value.entitlements.split(/[\n,]/).map((code) => code.trim().toLowerCase()).filter(Boolean))]
}

function statusLabel(value: MembershipPlanStatus) {
  return ({ draft: '草稿', published: '已发布', archived: '已归档' } as Record<MembershipPlanStatus, string>)[value]
}

function statusType(value: MembershipPlanStatus) {
  return value === 'published' ? 'success' : value === 'draft' ? 'warning' : 'info'
}

function dateTime(value: string) {
  return new Intl.DateTimeFormat('zh-CN', { dateStyle: 'short', timeStyle: 'short' }).format(new Date(value))
}

function resetForm() {
  form.value = { code: '', name: '', durationDays: 30, entitlements: '', priceAmount: 19.9, generationQuota: 10, assistantQuota: 300 }
}

function openCreate() {
  resetForm()
  createOpen.value = true
}

function openEdit(plan: MembershipPlan) {
  editForm.value = { id: plan.id, durationDays: plan.duration_days, priceAmount: Number(plan.price_amount), generationQuota: plan.generation_quota, assistantQuota: plan.assistant_quota, purchasable: plan.purchasable }
  editOpen.value = true
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    plans.value = await listMembershipPlans(status.value || undefined)
  } catch (cause) {
    plans.value = []
    error.value = normalizeApiError(cause).message
  } finally {
    loading.value = false
  }
}

async function submitCreate() {
  if (!canSubmit.value) return
  submitting.value = true
  try {
    await createMembershipPlan({
      code: form.value.code.trim(),
      name: form.value.name.trim(),
      duration_days: form.value.durationDays,
      entitlement_codes: entitlementCodes(),
      price_amount: form.value.priceAmount,
      currency: 'CNY',
      generation_quota: form.value.generationQuota,
      assistant_quota: form.value.assistantQuota,
      purchasable: false,
    })
    ElMessage.success('会员计划已保存为草稿。')
    createOpen.value = false
    await load()
  } catch (cause) {
    ElMessage.error(normalizeApiError(cause).message)
  } finally {
    submitting.value = false
  }
}

async function updateConfiguration(plan: MembershipPlan, changes: Parameters<typeof updateMembershipPlan>[1]) {
  actionId.value = plan.id
  try {
    await updateMembershipPlan(plan.id, changes)
    ElMessage.success('售卖配置已更新。')
    await load()
  } catch (cause) {
    ElMessage.error(normalizeApiError(cause).message)
  } finally {
    actionId.value = ''
  }
}

async function submitEdit() {
  if (!canUpdate.value) return
  submitting.value = true
  try {
    await updateMembershipPlan(editForm.value.id, {
      duration_days: editForm.value.durationDays,
      price_amount: editForm.value.priceAmount,
      currency: 'CNY',
      generation_quota: editForm.value.generationQuota,
      assistant_quota: editForm.value.assistantQuota,
      purchasable: editForm.value.purchasable,
    })
    ElMessage.success('售卖配置已更新。')
    editOpen.value = false
    await load()
  } catch (cause) {
    ElMessage.error(normalizeApiError(cause).message)
  } finally {
    submitting.value = false
  }
}

async function transition(plan: MembershipPlan, action: 'publish' | 'archive') {
  actionId.value = plan.id
  try {
    if (action === 'publish') await publishMembershipPlan(plan.id)
    else await archiveMembershipPlan(plan.id)
    ElMessage.success(action === 'publish' ? '会员计划已发布。' : '会员计划已归档。')
    await load()
  } catch (cause) {
    ElMessage.error(normalizeApiError(cause).message)
  } finally {
    actionId.value = ''
  }
}

onMounted(load)
</script>

<template>
  <main class="membership-plans-page">
    <section class="page-heading">
      <div>
        <h1>会员计划</h1>
        <p>维护会员售价、有效期、AI 额度与可售状态。购买授权与支付记录请在购买审计中处理。</p>
      </div>
      <div class="heading-actions">
        <button class="icon-action" type="button" title="刷新计划" :disabled="loading" @click="load"><RefreshCw :size="18" :class="{ spinning: loading }" /></button>
        <button class="primary-button" type="button" @click="openCreate"><Plus :size="18" />新建计划</button>
      </div>
    </section>

    <section class="policy-note" aria-label="会员计划操作范围">
      <strong>售卖规则</strong>
      <span>金额、时长和 AI 额度由服务端快照。</span>
      <span>仅已发布计划可设为可购买。</span>
      <RouterLink to="/memberships/purchases">查看购买审计</RouterLink>
    </section>

    <section class="workbench" aria-label="会员计划列表">
      <div class="filter-row">
        <el-select v-model="status" aria-label="计划状态筛选" placeholder="筛选状态" @change="load"><el-option v-for="option in statusOptions" :key="option[0]" :value="option[0]" :label="option[1]" /></el-select>
        <span>{{ loading ? '正在加载计划…' : `共 ${plans.length} 项，已发布 ${publishedCount} 项` }}</span>
      </div>
      <div v-if="error" class="error-state"><CircleAlert :size="20" /><div><strong>无法加载会员计划</strong><p>{{ error }}</p></div><button type="button" @click="load">重新尝试</button></div>
      <template v-else>
        <el-table :data="plans" v-loading="loading" row-key="id">
          <el-table-column label="计划" min-width="240"><template #default="{ row }"><strong>{{ row.name }}</strong><small>{{ row.code }}</small></template></el-table-column>
          <el-table-column label="售价" width="130"><template #default="{ row }">¥{{ Number(row.price_amount).toFixed(2) }}</template></el-table-column>
          <el-table-column label="有效期 / 额度" min-width="210"><template #default="{ row }"><div>{{ row.duration_days }} 天</div><small>{{ row.generation_quota }} 次行程 · {{ row.assistant_quota }} 次对话</small></template></el-table-column>
          <el-table-column label="权益代码" min-width="250"><template #default="{ row }"><div class="entitlements"><code v-for="code in row.entitlement_codes" :key="code">{{ code }}</code></div></template></el-table-column>
          <el-table-column label="状态 / 可售" width="160"><template #default="{ row }"><el-tag effect="plain" :type="statusType(row.status)">{{ statusLabel(row.status) }}</el-tag><el-switch :model-value="row.purchasable" :disabled="row.status !== 'published' || actionId === row.id" inline-prompt active-text="可售" inactive-text="停售" @update:model-value="updateConfiguration(row, { purchasable: $event })" /></template></el-table-column>
          <el-table-column label="更新于" min-width="158"><template #default="{ row }">{{ dateTime(row.updated_at) }}</template></el-table-column>
          <el-table-column label="操作" width="220" fixed="right"><template #default="{ row }"><button v-if="row.status !== 'archived'" class="text-action" type="button" :disabled="actionId === row.id" @click="openEdit(row)"><Pencil :size="16" />编辑</button><button v-if="row.status === 'draft'" class="text-action publish" type="button" :disabled="actionId === row.id" @click="transition(row, 'publish')"><Send :size="16" />发布</button><button v-if="row.status !== 'archived'" class="text-action archive" type="button" :disabled="actionId === row.id" @click="transition(row, 'archive')"><Archive :size="16" />归档</button><span v-if="row.status === 'archived'" class="muted">无可用操作</span></template></el-table-column>
        </el-table>
        <div v-if="!loading && !plans.length" class="empty-state">当前筛选条件下没有会员计划。</div>
      </template>
    </section>

    <el-dialog v-model="createOpen" width="min(560px, calc(100% - 32px))" title="新建会员计划" destroy-on-close @closed="resetForm">
      <form class="plan-form" @submit.prevent="submitCreate">
        <p>新计划将以草稿状态保存且默认停售。发布后才能开启购买。</p>
        <label>计划名称<el-input v-model="form.name" maxlength="160" placeholder="例如：行程探索会员" /></label>
        <label>计划代码<el-input v-model="form.code" maxlength="64" placeholder="例如：trip-explorer" /><small>小写字母、数字、连字符和下划线。</small></label>
        <label>有效期（天）<el-input-number v-model="form.durationDays" :min="1" :max="3650" controls-position="right" /></label>
        <label>售价（CNY）<el-input-number v-model="form.priceAmount" :min="0.01" :precision="2" :step="1" controls-position="right" /></label>
        <label>行程生成额度<el-input-number v-model="form.generationQuota" :min="0" :max="10000" controls-position="right" /></label>
        <label>AI 对话额度<el-input-number v-model="form.assistantQuota" :min="0" :max="1000000" controls-position="right" /></label>
        <label>权益代码<el-input v-model="form.entitlements" type="textarea" :rows="4" maxlength="6500" placeholder="每行一个，或以英文逗号分隔" /><small>重复项会合并；至少需要一项。</small></label>
        <div class="dialog-actions"><button class="secondary-button" type="button" @click="createOpen = false">取消</button><button class="primary-button" type="submit" :disabled="!canSubmit || submitting">{{ submitting ? '保存中…' : '保存草稿' }}</button></div>
      </form>
    </el-dialog>

    <el-dialog v-model="editOpen" width="min(520px, calc(100% - 32px))" title="编辑售卖配置" destroy-on-close>
      <form class="plan-form" @submit.prevent="submitEdit">
        <p>修改只影响后续购买的服务端快照，不变更已创建订单。</p>
        <label>有效期（天）<el-input-number v-model="editForm.durationDays" :min="1" :max="3650" controls-position="right" /></label>
        <label>售价（CNY）<el-input-number v-model="editForm.priceAmount" :min="0.01" :precision="2" :step="1" controls-position="right" /></label>
        <label>行程生成额度<el-input-number v-model="editForm.generationQuota" :min="0" :max="10000" controls-position="right" /></label>
        <label>AI 对话额度<el-input-number v-model="editForm.assistantQuota" :min="0" :max="1000000" controls-position="right" /></label>
        <el-switch v-model="editForm.purchasable" inline-prompt active-text="可售" inactive-text="停售" />
        <p class="form-note">草稿与已归档计划不可开启可售状态。</p>
        <div class="dialog-actions"><button class="secondary-button" type="button" @click="editOpen = false">取消</button><button class="primary-button" type="submit" :disabled="!canUpdate || submitting">{{ submitting ? '保存中…' : '保存配置' }}</button></div>
      </form>
    </el-dialog>
  </main>
</template>

<style scoped>
.membership-plans-page{margin:0 auto;max-width:1480px;padding:38px 42px 56px}.page-heading{align-items:flex-start;display:flex;gap:24px;justify-content:space-between;margin-bottom:24px}.page-heading h1{color:#142638;font-size:28px;letter-spacing:0;margin:0 0 8px}.page-heading p{color:#5e6b74;line-height:1.5;margin:0;max-width:760px}.heading-actions{display:flex;gap:10px}.icon-action,.primary-button,.secondary-button{align-items:center;border-radius:6px;cursor:pointer;display:inline-flex;font-weight:700;justify-content:center}.icon-action{background:#fff;border:1px solid #cbd5d9;color:#142638;height:38px;width:38px}.primary-button{background:#167a76;border:1px solid #167a76;color:#fff;gap:7px;min-height:38px;padding:0 14px}.secondary-button{background:#fff;border:1px solid #aebec3;color:#27404c;min-height:38px;padding:0 14px}.icon-action:disabled,.primary-button:disabled,.text-action:disabled{cursor:not-allowed;opacity:.55}.policy-note{align-items:center;background:#edf3f1;border:1px solid #d7e0df;color:#50636c;display:flex;flex-wrap:wrap;font-size:13px;gap:10px 20px;margin-bottom:20px;min-height:56px;padding:10px 20px}.policy-note strong{color:#142638}.policy-note span+span{border-left:1px solid #c9d8d4;padding-left:20px}.workbench{background:#fff;border:1px solid #d7e0df;min-height:320px}.filter-row{align-items:center;border-bottom:1px solid #d7e0df;display:flex;gap:14px;min-height:66px;padding:0 20px}.filter-row span{color:#667680;font-size:13px}.workbench :deep(.el-table){--el-table-header-bg-color:#edf3f1;--el-table-border-color:#d7e0df;--el-table-row-hover-bg-color:#f3f7f5}.workbench :deep(.el-table th.el-table__cell){color:#475762;font-size:12px;font-weight:700}.workbench :deep(.el-table td.el-table__cell){padding:13px 0}.workbench strong{color:#142638;display:block;font-weight:700}.workbench small{color:#829099;display:block;font-family:ui-monospace,monospace;font-size:11px;margin-top:4px}.entitlements{display:flex;flex-wrap:wrap;gap:5px}.entitlements code{background:#edf3f1;color:#27625f;font-family:ui-monospace,monospace;font-size:11px;padding:3px 5px}.text-action{align-items:center;background:none;border:0;cursor:pointer;display:inline-flex;font-size:13px;gap:4px;margin-right:12px;padding:4px 0}.text-action.publish{color:#167a76}.text-action.archive{color:#a45a2f}.muted{color:#829099;font-size:13px}.error-state{align-items:center;background:#fff5f2;color:#9f392b;display:flex;gap:12px;margin:20px;padding:18px}.error-state p{font-size:13px;margin:4px 0 0}.error-state button{background:none;border:0;color:inherit;cursor:pointer;margin-left:auto;text-decoration:underline}.empty-state{color:#64737d;padding:54px;text-align:center}.plan-form{display:grid;gap:18px}.plan-form>p{color:#5e6b74;line-height:1.5;margin:0}.plan-form label{color:#27404c;display:grid;font-size:14px;font-weight:700;gap:7px}.plan-form small{color:#71808a;font-size:12px;font-weight:400;line-height:1.4}.plan-form :deep(.el-input-number){width:180px}.dialog-actions{display:flex;gap:10px;justify-content:flex-end;margin-top:6px}.icon-action:focus-visible,.primary-button:focus-visible,.secondary-button:focus-visible,.text-action:focus-visible,.error-state button:focus-visible{outline:3px solid #d99824;outline-offset:2px}.spinning{animation:spin .8s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}@media(max-width:760px){.membership-plans-page{padding:26px 16px 40px}.page-heading{align-items:stretch;flex-direction:column}.heading-actions{justify-content:space-between}.policy-note{align-items:flex-start;flex-direction:column;gap:7px}.policy-note span+span{border-left:0;padding-left:0}.filter-row{align-items:flex-start;flex-direction:column;justify-content:center;padding:12px 16px}.dialog-actions{flex-direction:column-reverse}.dialog-actions button{width:100%}}
</style>
