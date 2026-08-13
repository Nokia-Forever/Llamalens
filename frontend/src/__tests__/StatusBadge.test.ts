import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import StatusBadge from '../components/StatusBadge.vue'

describe('StatusBadge', () => {
  it('succeeded 状态映射到 success 样式并显示状态文本', () => {
    const wrapper = mount(StatusBadge, { props: { status: 'succeeded' } })
    expect(wrapper.classes()).toContain('status-success')
    expect(wrapper.text()).toBe('succeeded')
  })

  it('failed 状态映射到 danger 样式', () => {
    const wrapper = mount(StatusBadge, { props: { status: 'failed' } })
    expect(wrapper.classes()).toContain('status-danger')
  })

  it('queued 状态映射到 warning 样式', () => {
    const wrapper = mount(StatusBadge, { props: { status: 'queued' } })
    expect(wrapper.classes()).toContain('status-warning')
  })

  it('未知状态映射到 neutral 样式', () => {
    const wrapper = mount(StatusBadge, { props: { status: 'unknown' } })
    expect(wrapper.classes()).toContain('status-neutral')
  })

  it('running 状态属于 success 类', () => {
    const wrapper = mount(StatusBadge, { props: { status: 'running' } })
    expect(wrapper.classes()).toContain('status-success')
  })

  it('label prop 覆盖默认文本', () => {
    const wrapper = mount(StatusBadge, { props: { status: 'succeeded', label: '成功' } })
    expect(wrapper.text()).toBe('成功')
  })
})
