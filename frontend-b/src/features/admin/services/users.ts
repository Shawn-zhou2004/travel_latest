import { api } from '@/services/api'

export interface AdminUser {
  id: string
  phone_masked: string
  nickname: string | null
  status: 'active' | 'suspended'
  roles: string[]
  provider_memberships: string[]
  created_at: string
  updated_at: string
}

export interface AdminUserPage { items: AdminUser[]; next_cursor: string | null }
export interface ListAdminUsersParams { query?: string; limit?: number; cursor?: string }

export async function listAdminUsers(params: ListAdminUsersParams = {}) {
  const { data } = await api.get<AdminUserPage>('/admin/users', { params })
  return data
}

export async function updateAdminUser(id: string, update: { status?: AdminUser['status'] }) {
  const { data } = await api.patch<AdminUser>(`/admin/users/${id}`, update)
  return data
}
