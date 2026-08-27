import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import ProfilePage from './ProfilePage.vue'

describe('ProfilePage', () => {
  it('directs the retired profile surface to the settings profile section', () => {
    const wrapper = mount(ProfilePage)
    expect(wrapper.text()).toContain('账户资料已迁移')
    expect(wrapper.get('a').attributes('href')).toBe('/me/settings#profile')
    expect(wrapper.find('form').exists()).toBe(false)
  })
})
