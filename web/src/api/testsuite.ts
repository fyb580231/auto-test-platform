/**
 * 用例集相关接口：CRUD、整套执行与调度器状态查询。
 */
import { httpDelete, httpGet, httpPost, httpPut } from '@/api/request'
import type {
  MessageResponse,
  RunSuitePayload,
  SchedulerJobsResponse,
  Task,
  TestSuite,
  TestSuitePayload,
  TestSuiteUpdatePayload,
} from '@/types'

/** 项目下的用例集列表 */
export function listSuites(projectId: number): Promise<TestSuite[]> {
  return httpGet<TestSuite[]>(`/projects/${projectId}/testsuites`)
}

/** 创建用例集 */
export function createSuite(projectId: number, payload: TestSuitePayload): Promise<TestSuite> {
  return httpPost<TestSuite>(`/projects/${projectId}/testsuites`, payload)
}

/** 用例集详情 */
export function getSuite(suiteId: number): Promise<TestSuite> {
  return httpGet<TestSuite>(`/testsuites/${suiteId}`)
}

/** 更新用例集（后端会同步调度器中的定时任务） */
export function updateSuite(suiteId: number, payload: TestSuiteUpdatePayload): Promise<TestSuite> {
  return httpPut<TestSuite>(`/testsuites/${suiteId}`, payload)
}

/** 删除用例集 */
export function deleteSuite(suiteId: number): Promise<MessageResponse> {
  return httpDelete<MessageResponse>(`/testsuites/${suiteId}`)
}

/** 执行整个用例集（异步，返回已创建的任务） */
export function runSuite(suiteId: number, payload: RunSuitePayload = {}): Promise<Task> {
  return httpPost<Task>(`/testsuites/${suiteId}/run`, payload)
}

/** 调度器状态与已注册的定时任务 */
export function getSchedulerJobs(): Promise<SchedulerJobsResponse> {
  return httpGet<SchedulerJobsResponse>('/scheduler/jobs')
}
