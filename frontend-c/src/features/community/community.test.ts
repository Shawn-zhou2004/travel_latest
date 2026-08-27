import { describe, expect, it } from 'vitest'
import { feedStateMessage } from './types'

describe('community states', () => {
  it('shows an explicit empty state', () => expect(feedStateMessage([], 'mysql')).toBe('No published posts match this view.'))
  it('prioritizes a loading error over feed hints', () => expect(feedStateMessage([], 'mysql_fallback', 'Could not load posts. Retry.')).toBe('Could not load posts. Retry.'))
})
