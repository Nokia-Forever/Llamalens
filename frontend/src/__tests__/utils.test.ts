import { describe, it, expect } from 'vitest'
import { cloneConfig, formatDate } from '../utils'

describe('cloneConfig', () => {
  it('深拷贝普通对象，修改副本不影响原对象', () => {
    const source = { a: 1, nested: { b: 2 } }
    const copy = cloneConfig(source)
    expect(copy).not.toBe(source)
    expect(copy).toEqual(source)
    copy.nested.b = 99
    expect(source.nested.b).toBe(2)
  })

  it('深拷贝数组', () => {
    const source = { list: [1, 2, 3] }
    const copy = cloneConfig(source)
    expect(copy.list).toEqual([1, 2, 3])
    expect(copy.list).not.toBe(source.list)
  })

  it('深拷贝 Date 对象', () => {
    const date = new Date('2024-01-01T00:00:00Z')
    const copy = cloneConfig({ created: date })
    expect(copy.created).toEqual(date)
    expect(copy.created).not.toBe(date)
  })

  it('深拷贝基本类型', () => {
    expect(cloneConfig(42)).toBe(42)
    expect(cloneConfig('hello')).toBe('hello')
  })
})

describe('formatDate', () => {
  it('null 返回 N/A', () => {
    expect(formatDate(null)).toBe('N/A')
  })

  it('undefined 返回 N/A', () => {
    expect(formatDate(undefined)).toBe('N/A')
  })

  it('空字符串返回 N/A', () => {
    expect(formatDate('')).toBe('N/A')
  })

  it('带 Z 的 ISO 字符串可解析', () => {
    const result = formatDate('2024-06-15T10:30:00Z')
    expect(result).not.toBe('N/A')
    expect(result).toContain('2024')
  })

  it('不带时区后缀的字符串补 Z', () => {
    const result = formatDate('2024-06-15T10:30:00')
    expect(result).not.toBe('N/A')
  })
})
