export * from './api/index'
import { request } from './api/client'

export const api = request

export function jsonBody(value: unknown): { body: unknown } {
  return { body: value }
}
