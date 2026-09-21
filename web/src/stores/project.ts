/**
 * 项目状态管理：项目列表与「当前项目」。
 *
 * 用例管理、用例集、执行历史、环境配置都以「当前项目」为上下文，
 * 因此当前项目 ID 持久化到 localStorage，刷新后仍然保持。
 */
import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import { listProjects } from '@/api/project'
import type { Project } from '@/types'

/** localStorage 中的当前项目键名 */
const PROJECT_KEY = 'atp_current_project_id'

/** 读取本地缓存的当前项目 ID */
function readCachedProjectId(): number | null {
  const raw = localStorage.getItem(PROJECT_KEY)
  if (!raw) return null
  const parsed = Number(raw)
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null
}

export const useProjectStore = defineStore('project', () => {
  /** 项目列表 */
  const projects = ref<Project[]>([])
  /** 当前项目 ID */
  const currentProjectId = ref<number | null>(readCachedProjectId())
  /** 列表加载状态 */
  const loading = ref(false)

  /** 当前项目对象（从列表里派生，保证统计字段始终是最新的） */
  const currentProject = computed<Project | null>(
    () => projects.value.find((item) => item.id === currentProjectId.value) ?? null,
  )

  /** 是否已选择项目 */
  const hasProject = computed<boolean>(() => currentProject.value !== null)

  /** 加载项目列表；若当前项目已不存在则清空，避免页面停留在无效上下文 */
  async function loadProjects(keyword?: string): Promise<Project[]> {
    loading.value = true
    try {
      const list = await listProjects(keyword)
      projects.value = list
      if (currentProjectId.value && !list.some((item) => item.id === currentProjectId.value)) {
        setCurrentProject(null)
      }
      return list
    } finally {
      loading.value = false
    }
  }

  /** 切换当前项目并持久化 */
  function setCurrentProject(projectId: number | null): void {
    currentProjectId.value = projectId
    if (projectId) {
      localStorage.setItem(PROJECT_KEY, String(projectId))
    } else {
      localStorage.removeItem(PROJECT_KEY)
    }
  }

  return {
    projects,
    currentProjectId,
    currentProject,
    hasProject,
    loading,
    loadProjects,
    setCurrentProject,
  }
})
