/**
 * axios 实例与拦截器：全局唯一的 HTTP 出口。
 *
 * 职责：
 * 1. `baseURL` 固定为 `/api`，开发环境由 vite proxy 转发，前端不硬编码后端地址；
 * 2. 请求拦截器注入 `Authorization: Bearer <token>`；
 * 3. 响应拦截器统一处理失败响应（弹出 `message` 与 `data.errors`），401 时清理 token 并跳登录页；
 * 4. 对外暴露 `httpGet / httpPost / httpPut / httpDelete` 四个泛型方法，调用方直接拿到数据体。
 */
import axios, { AxiosError, type AxiosInstance, type InternalAxiosRequestConfig } from 'axios'
import { ElMessage } from 'element-plus'

import type { ApiErrorResponse } from '@/types'

/** localStorage 中的 token 键名 */
const TOKEN_KEY = 'atp_token'

/** 请求超时时间：30 秒（AI 生成用例等接口耗时较长，但仍在 30s 内） */
const HTTP_TIMEOUT = 30_000

/** 读取本地保存的 token */
export function getToken(): string {
  return localStorage.getItem(TOKEN_KEY) ?? ''
}

/** 保存 token 到本地 */
export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token)
}

/** 清除本地 token */
export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY)
}

/** 过滤掉 undefined / null / 空字符串的查询参数，避免拼出 `?tag=&keyword=` 这类脏 URL */
export function pruneParams(source: Record<string, unknown>): Record<string, unknown> {
  const result: Record<string, unknown> = {}
  Object.entries(source).forEach(([key, value]) => {
    if (value === undefined || value === null || value === '') return
    result[key] = value
  })
  return result
}

const service: AxiosInstance = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '/api',
  timeout: HTTP_TIMEOUT,
})

service.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const token = getToken()
  if (token) {
    config.headers.set('Authorization', `Bearer ${token}`)
  }
  return config
})

/** 从失败响应中提取可读的错误文案 */
function resolveErrorMessage(error: AxiosError<ApiErrorResponse>): string {
  const body = error.response?.data
  if (body && typeof body === 'object' && typeof body.message === 'string' && body.message) {
    return body.message
  }
  if (typeof body === 'string' && body) {
    return body
  }
  if (error.code === 'ECONNABORTED' || error.message.includes('timeout')) {
    return '请求超时（30 秒），请确认后端服务是否正常'
  }
  if (!error.response) {
    return '无法连接后端服务，请确认后端已在 127.0.0.1:8000 启动'
  }
  return error.message || '请求失败'
}

/** 提取后端返回的字段级校验错误（Pydantic 422 的 data.errors） */
function resolveDetailErrors(error: AxiosError<ApiErrorResponse>): string[] {
  const errors = error.response?.data?.data?.errors
  return Array.isArray(errors) ? errors.filter((item): item is string => typeof item === 'string') : []
}

service.interceptors.response.use(
  (response) => response,
  (error: AxiosError<ApiErrorResponse>) => {
    const status = error.response?.status
    if (status === 401) {
      clearToken()
      ElMessage.error('登录状态已失效，请重新登录')
      if (!window.location.pathname.startsWith('/login')) {
        window.location.replace('/login')
      }
      return Promise.reject(error)
    }

    const details = resolveDetailErrors(error)
    const message = resolveErrorMessage(error)
    ElMessage.error(details.length ? `${message}：${details.join('；')}` : message)
    return Promise.reject(error)
  },
)

/** GET 请求 */
export async function httpGet<T>(url: string, params?: Record<string, unknown>): Promise<T> {
  const response = await service.get<T>(url, { params })
  return response.data
}

/** POST 请求（`params` 用于 `/run?environment_id=1` 这类查询参数） */
export async function httpPost<T>(
  url: string,
  payload?: unknown,
  params?: Record<string, unknown>,
): Promise<T> {
  const response = await service.post<T>(url, payload ?? {}, { params })
  return response.data
}

/** PUT 请求 */
export async function httpPut<T>(url: string, payload?: unknown): Promise<T> {
  const response = await service.put<T>(url, payload ?? {})
  return response.data
}

/** DELETE 请求 */
export async function httpDelete<T>(url: string, params?: Record<string, unknown>): Promise<T> {
  const response = await service.delete<T>(url, { params })
  return response.data
}

export default service
