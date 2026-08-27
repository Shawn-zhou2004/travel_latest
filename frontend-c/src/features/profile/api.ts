import { api } from '@/services/api'

export interface Profile {
  id: string
  phone: string
  nickname: string | null
  avatar_asset_id: string | null
}

export function getMyProfile() {
  return api.get<Profile>('/auth/me').then(({ data }) => data)
}

export function updateMyProfile(changes: Partial<Pick<Profile, 'nickname' | 'avatar_asset_id'>>) {
  return api.patch<Profile>('/users/me', changes).then(({ data }) => data)
}
