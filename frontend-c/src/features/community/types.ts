export interface CommunityPost {
  id: string
  author_id: string
  title: string
  body_text: string
  city_code?: string | null
  status: 'draft' | 'pending_review' | 'published' | 'hidden' | 'rejected'
  published_at?: string | null
}

export interface CommunityPageResult { items: CommunityPost[]; next_cursor: string | null }

export interface CommunityComment {
  id: string
  post_id: string
  author_id: string
  parent_id: string | null
  body_text: string
  created_at: string
}

export type SearchSource = 'mysql' | 'mysql_fallback'

export function feedStateMessage(posts: CommunityPost[], source: SearchSource, error?: string): string {
  if (error) return error
  if (posts.length === 0) return 'No published posts match this view.'
  return ''
}
