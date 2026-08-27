import { api } from '@/services/api'

export interface ChecklistItem { id: string; category: string; content: string; checked: boolean; source: string }
export interface BudgetItem { id: string; category: string; amount: string; currency: string; description: string | null }
export interface BudgetTotal { currency: string; total_amount: string }

export async function getChecklist(itineraryId: string) {
  const { data } = await api.get<{ items: ChecklistItem[] }>(`/itineraries/${itineraryId}/checklists`)
  return data.items
}
export async function createChecklist(itineraryId: string, payload: Pick<ChecklistItem, 'category' | 'content'>) {
  const { data } = await api.post<ChecklistItem>(`/itineraries/${itineraryId}/checklists`, payload)
  return data
}
export async function updateChecklist(itineraryId: string, itemId: string, payload: Partial<Pick<ChecklistItem, 'category' | 'content' | 'checked'>>) {
  const { data } = await api.patch<ChecklistItem>(`/itineraries/${itineraryId}/checklists/${itemId}`, payload)
  return data
}
export async function deleteChecklist(itineraryId: string, itemId: string) { await api.delete(`/itineraries/${itineraryId}/checklists/${itemId}`) }
export async function getBudget(itineraryId: string) {
  const { data } = await api.get<{ items: BudgetItem[]; totals: BudgetTotal[] }>(`/itineraries/${itineraryId}/budgets`)
  return data
}
export async function createBudget(itineraryId: string, payload: Pick<BudgetItem, 'category' | 'amount' | 'currency' | 'description'>) {
  const { data } = await api.post<BudgetItem>(`/itineraries/${itineraryId}/budgets`, payload)
  return data
}
export async function updateBudget(itineraryId: string, itemId: string, payload: Partial<Pick<BudgetItem, 'category' | 'amount' | 'description'>>) {
  const { data } = await api.patch<BudgetItem>(`/itineraries/${itineraryId}/budgets/${itemId}`, payload)
  return data
}
export async function deleteBudget(itineraryId: string, itemId: string) { await api.delete(`/itineraries/${itineraryId}/budgets/${itemId}`) }
