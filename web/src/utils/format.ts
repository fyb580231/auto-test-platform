/**
 * 展示层格式化工具：时间、耗时、状态文案与颜色等。
 *
 * 这些函数被多个页面复用（任务列表、报告、Dashboard），
 * 集中在一处可以保证同一份数据在不同页面上的展示口径一致。
 */
import type { CaseResultStatus, CaseType, JsonValue, TaskStatus } from '@/types'

/** 把 ISO 时间字符串格式化为 `YYYY-MM-DD HH:mm:ss`；空值显示为 `-` */
export function formatDateTime(value: string | null | undefined): string {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value)
  const pad = (num: number): string => String(num).padStart(2, '0')
  return (
    `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ` +
    `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`
  )
}

/** 把 ISO 时间字符串格式化为 `MM-DD`（图表 X 轴用） */
export function formatShortDate(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  const pad = (num: number): string => String(num).padStart(2, '0')
  return `${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}

/** 毫秒耗时格式化：小于 1s 显示毫秒，否则显示秒 */
export function formatDuration(ms: number | null | undefined): string {
  if (!ms || ms <= 0) return '-'
  if (ms < 1000) return `${Math.round(ms)} ms`
  return `${(ms / 1000).toFixed(2)} s`
}

/** 任务编号只展示尾段，避免表格列过宽 */
export function shortTaskNo(taskNo: string): string {
  if (!taskNo) return '-'
  return taskNo.length > 12 ? taskNo.slice(-12) : taskNo
}

/** 任务状态 -> 中文文案 */
export function taskStatusText(status: TaskStatus): string {
  const map: Record<TaskStatus, string> = {
    pending: '等待中',
    running: '执行中',
    success: '成功',
    failed: '失败',
    error: '执行异常',
  }
  return map[status] ?? status
}

type TagType = 'success' | 'info' | 'warning' | 'danger' | 'primary'

/** 任务状态 -> Element Plus Tag 颜色 */
export function taskStatusTagType(status: TaskStatus): TagType {
  const map: Record<TaskStatus, TagType> = {
    pending: 'info',
    running: 'primary',
    success: 'success',
    failed: 'danger',
    error: 'warning',
  }
  return map[status] ?? 'info'
}

/** 用例结果状态 -> 中文文案 */
export function caseStatusText(status: CaseResultStatus): string {
  const map: Record<CaseResultStatus, string> = {
    passed: '通过',
    failed: '失败',
    error: '执行异常',
    skipped: '跳过',
  }
  return map[status] ?? status
}

/** 用例结果状态 -> Element Plus Tag 颜色 */
export function caseStatusTagType(status: CaseResultStatus): TagType {
  const map: Record<CaseResultStatus, TagType> = {
    passed: 'success',
    failed: 'danger',
    error: 'warning',
    skipped: 'info',
  }
  return map[status] ?? 'info'
}

/** 用例类型 -> 中文文案 */
export function caseTypeText(caseType: CaseType): string {
  return caseType === 'ui' ? 'UI' : '接口'
}

/** 触发来源 -> 中文文案 */
export function triggerTypeText(triggerType: string): string {
  const map: Record<string, string> = {
    manual: '手工触发',
    schedule: '定时调度',
    suite: '用例集',
    retry: '重跑',
  }
  return map[triggerType] ?? triggerType
}

/** 触发来源 -> Element Plus Tag 颜色 */
export function triggerTypeTagType(triggerType: string): TagType {
  const map: Record<string, TagType> = {
    manual: 'info',
    schedule: 'warning',
    suite: 'primary',
    retry: 'danger',
  }
  return map[triggerType] ?? 'info'
}

/** 安全地格式化 JSON 值，用于 `<pre>` 展示（不可序列化时回退到 String） */
export function prettyJson(value: JsonValue | undefined, emptyText = '无'): string {
  if (value === undefined || value === null || value === '') return emptyText
  if (typeof value === 'string') return value
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

/** 判断对象是否有实际内容（用于「无请求头」这类空态展示） */
export function isEmptyObject(value: JsonValue | null | undefined): boolean {
  if (value === null || value === undefined) return true
  if (typeof value !== 'object') return false
  return Object.keys(value).length === 0
}
