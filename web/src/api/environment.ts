/**
 * 环境配置相关接口：项目下的环境 CRUD。
 */
import { httpDelete, httpGet, httpPost, httpPut } from '@/api/request'
import type { Environment, EnvironmentPayload, EnvironmentUpdatePayload, MessageResponse } from '@/types'

/** 项目下的环境列表 */
export function listEnvironments(projectId: number): Promise<Environment[]> {
  return httpGet<Environment[]>(`/projects/${projectId}/environments`)
}

/** 创建环境 */
export function createEnvironment(
  projectId: number,
  payload: EnvironmentPayload,
): Promise<Environment> {
  return httpPost<Environment>(`/projects/${projectId}/environments`, payload)
}

/** 更新环境（后端已保证同项目下默认环境唯一） */
export function updateEnvironment(
  environmentId: number,
  payload: EnvironmentUpdatePayload,
): Promise<Environment> {
  return httpPut<Environment>(`/environments/${environmentId}`, payload)
}

/** 删除环境 */
export function deleteEnvironment(environmentId: number): Promise<MessageResponse> {
  return httpDelete<MessageResponse>(`/environments/${environmentId}`)
}
