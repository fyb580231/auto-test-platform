/**
 * 用例相关接口：列表查询、CRUD、批量导入、单条与批量执行。
 */
import { httpDelete, httpGet, httpPost, httpPut, pruneParams } from '@/api/request'
import type {
  BatchRunPayload,
  CasePayload,
  CaseQuery,
  CaseUpdatePayload,
  ImportCasesPayload,
  ImportResult,
  MessageResponse,
  PageResult,
  Task,
  TestCase,
} from '@/types'

/** 用例列表（分页 + 类型/标签/关键字/启用状态过滤） */
export function listCases(projectId: number, query: CaseQuery = {}): Promise<PageResult<TestCase>> {
  return httpGet<PageResult<TestCase>>(
    `/projects/${projectId}/testcases`,
    pruneParams({
      case_type: query.case_type,
      tag: query.tag,
      keyword: query.keyword,
      enabled: query.enabled,
      page: query.page,
      size: query.size,
    }),
  )
}

/** 创建用例 */
export function createCase(projectId: number, payload: CasePayload): Promise<TestCase> {
  return httpPost<TestCase>(`/projects/${projectId}/testcases`, payload)
}

/** 用例详情 */
export function getCase(caseId: number): Promise<TestCase> {
  return httpGet<TestCase>(`/testcases/${caseId}`)
}

/** 更新用例（字段可选） */
export function updateCase(caseId: number, payload: CaseUpdatePayload): Promise<TestCase> {
  return httpPut<TestCase>(`/testcases/${caseId}`, payload)
}

/** 删除用例 */
export function deleteCase(caseId: number): Promise<MessageResponse> {
  return httpDelete<MessageResponse>(`/testcases/${caseId}`)
}

/** 批量导入用例（AI 生成结果落库也走这里） */
export function importCases(
  projectId: number,
  payload: ImportCasesPayload,
): Promise<MessageResponse<ImportResult>> {
  return httpPost<MessageResponse<ImportResult>>(`/projects/${projectId}/testcases/import`, payload)
}

/** 执行单条用例（异步，返回已创建的任务） */
export function runCase(caseId: number, environmentId?: number | null): Promise<Task> {
  return httpPost<Task>(`/testcases/${caseId}/run`, {}, pruneParams({ environment_id: environmentId }))
}

/** 批量执行用例（异步，返回已创建的任务） */
export function batchRunCases(payload: BatchRunPayload): Promise<Task> {
  return httpPost<Task>('/testcases/batch-run', payload)
}
