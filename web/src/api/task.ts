/**
 * 执行任务与报告相关接口：任务列表、详情、日志、重跑、删除。
 */
import { httpDelete, httpGet, httpPost, pruneParams } from '@/api/request'
import type { MessageResponse, PageResult, Task, TaskDetail, TaskLog, TaskQuery } from '@/types'

/** 任务列表（分页 + 项目/状态/触发来源/关键字过滤） */
export function listTasks(query: TaskQuery = {}): Promise<PageResult<Task>> {
  return httpGet<PageResult<Task>>(
    '/tasks',
    pruneParams({
      project_id: query.project_id,
      status: query.status,
      trigger_type: query.trigger_type,
      keyword: query.keyword,
      page: query.page,
      size: query.size,
    }),
  )
}

/** 任务详情（含每条用例的请求/响应/断言/截图明细） */
export function getTask(taskId: number): Promise<TaskDetail> {
  return httpGet<TaskDetail>(`/tasks/${taskId}`)
}

/** 任务控制台日志 */
export function getTaskLog(taskId: number): Promise<TaskLog> {
  return httpGet<TaskLog>(`/tasks/${taskId}/log`)
}

/** 用相同用例与配置重跑一次 */
export function retryTask(taskId: number): Promise<Task> {
  return httpPost<Task>(`/tasks/${taskId}/retry`)
}

/** 删除任务记录 */
export function deleteTask(taskId: number): Promise<MessageResponse> {
  return httpDelete<MessageResponse>(`/tasks/${taskId}`)
}
