/**
 * Dashboard 统计接口。
 */
import { httpGet } from '@/api/request'
import type { DashboardStats } from '@/types'

/** 首页统计：概览卡片、通过率趋势、项目维度统计、失败分布、最近任务 */
export function getDashboardStats(days = 7): Promise<DashboardStats> {
  return httpGet<DashboardStats>('/dashboard/stats', { days })
}
