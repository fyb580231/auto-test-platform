/**
 * 项目相关接口：CRUD 与标签查询。
 */
import { httpDelete, httpGet, httpPost, httpPut, pruneParams } from '@/api/request'
import type { MessageResponse, Project, ProjectPayload } from '@/types'

/** 项目列表（可按关键字过滤） */
export function listProjects(keyword?: string): Promise<Project[]> {
  return httpGet<Project[]>('/projects', pruneParams({ keyword: keyword ?? '' }))
}

/** 创建项目 */
export function createProject(payload: ProjectPayload): Promise<Project> {
  return httpPost<Project>('/projects', payload)
}

/** 项目详情 */
export function getProject(projectId: number): Promise<Project> {
  return httpGet<Project>(`/projects/${projectId}`)
}

/** 更新项目 */
export function updateProject(projectId: number, payload: Partial<ProjectPayload>): Promise<Project> {
  return httpPut<Project>(`/projects/${projectId}`, payload)
}

/** 删除项目（级联删除其下用例、用例集、环境） */
export function deleteProject(projectId: number): Promise<MessageResponse> {
  return httpDelete<MessageResponse>(`/projects/${projectId}`)
}

/** 项目内已使用的标签（供筛选下拉框与编辑器候选标签使用） */
export function listProjectTags(projectId: number): Promise<string[]> {
  return httpGet<string[]>(`/projects/${projectId}/tags`)
}
