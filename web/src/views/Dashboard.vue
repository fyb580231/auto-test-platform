<!--
  Dashboard.vue —— 首页概览。

  职责：
  1. 顶部统计卡片：项目数 / 用例数 / 用例集数 / 近 7 天任务数 / 通过率 / 失败任务数；
  2. ECharts 折线图：近 7 天通过率趋势（双 Y 轴：通过率 % + 执行用例数）；
  3. ECharts 饼图：失败用例 TOP 分布；
  4. ECharts 横向柱状图：各项目通过率对比；
  5. 最近执行任务表格（点击跳转执行历史）；
  6. 右侧悬浮入口打开 AI 助手抽屉。
-->
<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import * as echarts from 'echarts'
import type { EChartsOption } from 'echarts'
import { ElMessage } from 'element-plus'
import { MagicStick, Refresh } from '@element-plus/icons-vue'

import { getDashboardStats } from '@/api/dashboard'
import AiAssistant from '@/components/AiAssistant.vue'
import type { DashboardStats, Task } from '@/types'
import {
  formatDateTime,
  formatDuration,
  formatShortDate,
  taskStatusTagType,
  taskStatusText,
} from '@/utils/format'

/** 统计窗口天数（与后端默认口径保持一致） */
const STAT_DAYS = 7

const router = useRouter()

const loading = ref(false)
const stats = ref<DashboardStats | null>(null)
const aiVisible = ref(false)

/** 概览卡片配置 */
interface StatCard {
  label: string
  value: string
  hint: string
  accent: string
}

const statCards = computed<StatCard[]>(() => {
  const summary = stats.value?.summary
  if (!summary) return []
  return [
    { label: '项目数', value: String(summary.project_count), hint: '全部项目', accent: '#409eff' },
    { label: '用例数', value: String(summary.case_count), hint: '接口 + UI 用例', accent: '#409eff' },
    { label: '用例集数', value: String(summary.suite_count), hint: '支持定时调度', accent: '#409eff' },
    {
      label: `近 ${STAT_DAYS} 天任务数`,
      value: String(summary.task_count_7d),
      hint: '含未结束任务',
      accent: '#e6a23c',
    },
    {
      label: `近 ${STAT_DAYS} 天通过率`,
      value: `${summary.pass_rate_7d.toFixed(1)}%`,
      hint: '按用例数加权计算',
      accent: '#67c23a',
    },
    {
      label: '失败任务数',
      value: String(summary.failed_task_count_7d),
      hint: `平均耗时 ${formatDuration(summary.avg_duration_ms)}`,
      accent: '#f56c6c',
    },
  ]
})

/* ------------------------------ ECharts ------------------------------ */
type ChartInstance = ReturnType<typeof echarts.init>

const trendRef = ref<HTMLDivElement>()
const failRef = ref<HTMLDivElement>()
const projectRef = ref<HTMLDivElement>()

let trendChart: ChartInstance | null = null
let failChart: ChartInstance | null = null
let projectChart: ChartInstance | null = null

/** 近 7 天通过率趋势：折线（通过率）+ 柱状（执行用例数），双 Y 轴 */
function buildTrendOption(): EChartsOption {
  const trend = stats.value?.trend ?? []
  return {
    tooltip: { trigger: 'axis' },
    legend: { data: ['通过率', '执行用例数'], top: 0, right: 0 },
    grid: { left: 56, right: 56, top: 40, bottom: 28 },
    xAxis: {
      type: 'category',
      data: trend.map((point) => formatShortDate(point.date)),
      axisTick: { show: false },
    },
    yAxis: [
      {
        type: 'value',
        name: '通过率 %',
        min: 0,
        max: 100,
        axisLabel: { formatter: '{value}%' },
        splitLine: { lineStyle: { type: 'dashed' } },
      },
      {
        type: 'value',
        name: '用例数',
        minInterval: 1,
        splitLine: { show: false },
      },
    ],
    series: [
      {
        name: '通过率',
        type: 'line',
        smooth: true,
        yAxisIndex: 0,
        symbolSize: 7,
        data: trend.map((point) => Number(point.pass_rate.toFixed(2))),
        itemStyle: { color: '#409eff' },
        areaStyle: { opacity: 0.08 },
      },
      {
        name: '执行用例数',
        type: 'bar',
        yAxisIndex: 1,
        barMaxWidth: 20,
        data: trend.map((point) => point.total),
        itemStyle: { color: '#c6e2ff' },
      },
    ],
  }
}

/** 失败用例 TOP 分布 */
function buildFailOption(): EChartsOption {
  const distribution = stats.value?.fail_distribution ?? []
  return {
    tooltip: { trigger: 'item', formatter: '{b}: {c} 次失败 ({d}%)' },
    legend: { type: 'scroll', orient: 'vertical', right: 0, top: 'middle', itemWidth: 10, itemHeight: 10 },
    series: [
      {
        name: '失败次数',
        type: 'pie',
        radius: ['45%', '68%'],
        center: ['38%', '52%'],
        avoidLabelOverlap: true,
        itemStyle: { borderColor: '#fff', borderWidth: 2 },
        label: { show: false },
        emphasis: { label: { show: true, fontWeight: 600 } },
        data: distribution.map((item) => ({ name: item.name, value: item.value })),
      },
    ],
  }
}

/** 各项目通过率（横向柱状图，按通过率升序，便于一眼看出最差的项目） */
function buildProjectOption(): EChartsOption {
  const projectStats = [...(stats.value?.project_stats ?? [])].sort(
    (left, right) => left.pass_rate - right.pass_rate,
  )
  return {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: '{b}<br/>通过率：{c}%',
    },
    grid: { left: 8, right: 48, top: 16, bottom: 8, containLabel: true },
    xAxis: { type: 'value', min: 0, max: 100, axisLabel: { formatter: '{value}%' } },
    yAxis: {
      type: 'category',
      data: projectStats.map((item) => item.project_name),
      axisTick: { show: false },
    },
    series: [
      {
        name: '通过率',
        type: 'bar',
        barMaxWidth: 18,
        label: { show: true, position: 'right', formatter: '{c}%' },
        data: projectStats.map((item) => ({
          value: Number(item.pass_rate.toFixed(2)),
          // 用颜色分档代替渐变：>=90% 绿、>=70% 橙、其余红
          itemStyle: {
            color: item.pass_rate >= 90 ? '#67c23a' : item.pass_rate >= 70 ? '#e6a23c' : '#f56c6c',
          },
        })),
      },
    ],
  }
}

/** 渲染（或更新）三张图表 */
function renderCharts(): void {
  if (trendRef.value) {
    trendChart = trendChart ?? echarts.init(trendRef.value)
    trendChart.setOption(buildTrendOption(), true)
  }
  if (failRef.value) {
    failChart = failChart ?? echarts.init(failRef.value)
    failChart.setOption(buildFailOption(), true)
  }
  if (projectRef.value) {
    projectChart = projectChart ?? echarts.init(projectRef.value)
    projectChart.setOption(buildProjectOption(), true)
  }
}

/** 容器尺寸变化时重绘 */
function handleResize(): void {
  trendChart?.resize()
  failChart?.resize()
  projectChart?.resize()
}

watch(stats, () => {
  void nextTick(renderCharts)
})

/* ------------------------------ 数据加载 ------------------------------ */
async function loadStats(): Promise<void> {
  loading.value = true
  try {
    stats.value = await getDashboardStats(STAT_DAYS)
  } catch {
    // 错误提示已由 axios 拦截器统一处理
  } finally {
    loading.value = false
  }
}

async function handleRefresh(): Promise<void> {
  await loadStats()
  ElMessage.success('统计数据已刷新')
}

/** 点击最近任务行跳转到执行历史 */
function goTaskDetail(task: Task): void {
  void router.push({ path: '/tasks', query: { taskId: String(task.id) } })
}

onMounted(() => {
  void loadStats()
  window.addEventListener('resize', handleResize)
  void nextTick(renderCharts)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', handleResize)
  trendChart?.dispose()
  failChart?.dispose()
  projectChart?.dispose()
  trendChart = null
  failChart = null
  projectChart = null
})
</script>

<template>
  <div v-loading="loading" class="dashboard">
    <div class="dashboard__toolbar">
      <div>
        <h2 class="dashboard__title">运行概览</h2>
        <p class="dashboard__desc">统计窗口：最近 {{ STAT_DAYS }} 天（与后端统计口径一致）</p>
      </div>
      <el-button :icon="Refresh" @click="handleRefresh">刷新</el-button>
    </div>

    <el-row :gutter="16">
      <el-col v-for="card in statCards" :key="card.label" :xs="12" :sm="8" :md="4">
        <div class="stat-card">
          <div class="stat-card__label">{{ card.label }}</div>
          <div class="stat-card__value" :style="{ color: card.accent }">{{ card.value }}</div>
          <div class="stat-card__hint">{{ card.hint }}</div>
        </div>
      </el-col>
    </el-row>

    <el-row :gutter="16" class="dashboard__row">
      <el-col :xs="24" :lg="14">
        <el-card shadow="never" class="chart-card">
          <template #header>
            <div class="chart-card__header">
              <span>通过率趋势</span>
              <span class="chart-card__sub">左轴：通过率 % · 右轴：执行用例数</span>
            </div>
          </template>
          <div ref="trendRef" class="chart chart--line" />
        </el-card>
      </el-col>
      <el-col :xs="24" :lg="10">
        <el-card shadow="never" class="chart-card">
          <template #header>
            <div class="chart-card__header">
              <span>失败用例 TOP 分布</span>
              <span class="chart-card__sub">按失败次数排序</span>
            </div>
          </template>
          <div v-if="stats?.fail_distribution.length" ref="failRef" class="chart chart--pie" />
          <el-empty v-else description="统计窗口内暂无失败用例" :image-size="80" />
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="16" class="dashboard__row">
      <el-col :xs="24" :lg="14">
        <el-card shadow="never" class="chart-card">
          <template #header>
            <div class="chart-card__header">
              <span>各项目通过率</span>
              <span class="chart-card__sub">按通过率升序，便于定位质量短板</span>
            </div>
          </template>
          <div v-if="stats?.project_stats.length" ref="projectRef" class="chart chart--bar" />
          <el-empty v-else description="统计窗口内暂无已结束的任务" :image-size="80" />
        </el-card>
      </el-col>
      <el-col :xs="24" :lg="10">
        <el-card shadow="never" class="chart-card">
          <template #header>
            <div class="chart-card__header">
              <span>最近执行任务</span>
              <el-link type="primary" :underline="false" @click="router.push('/tasks')">
                查看全部
              </el-link>
            </div>
          </template>
          <el-table
            :data="stats?.recent_tasks ?? []"
            size="small"
            height="300"
            @row-click="goTaskDetail"
          >
            <el-table-column prop="name" label="任务名称" min-width="150" show-overflow-tooltip />
            <el-table-column label="状态" width="90">
              <template #default="{ row }">
                <el-tag :type="taskStatusTagType(row.status)" size="small" effect="light">
                  {{ taskStatusText(row.status) }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="通过率" width="90">
              <template #default="{ row }">{{ row.total ? `${row.pass_rate.toFixed(1)}%` : '-' }}</template>
            </el-table-column>
            <el-table-column label="开始时间" width="160">
              <template #default="{ row }">{{ formatDateTime(row.started_at ?? row.created_at) }}</template>
            </el-table-column>
            <template #empty>
              <span class="dashboard__empty">暂无执行记录</span>
            </template>
          </el-table>
        </el-card>
      </el-col>
    </el-row>

    <div class="ai-entry">
      <el-button type="primary" :icon="MagicStick" @click="aiVisible = true">AI 助手</el-button>
    </div>

    <AiAssistant v-model="aiVisible" />
  </div>
</template>

<style scoped>
.dashboard {
  min-height: 100%;
}

.dashboard__toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
}

.dashboard__title {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
}

.dashboard__desc {
  margin: 4px 0 0;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.dashboard__row {
  margin-top: 16px;
}

.stat-card {
  margin-bottom: 16px;
  padding: 16px;
  background-color: #ffffff;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
}

.stat-card__label {
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.stat-card__value {
  margin: 8px 0 4px;
  font-size: 24px;
  font-weight: 600;
  line-height: 1.2;
}

.stat-card__hint {
  font-size: 12px;
  color: var(--el-text-color-placeholder);
}

.chart-card {
  margin-bottom: 16px;
  border-color: var(--el-border-color-lighter);
}

.chart-card__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 14px;
  font-weight: 600;
}

.chart-card__sub {
  font-size: 12px;
  font-weight: 400;
  color: var(--el-text-color-secondary);
}

.chart--line {
  height: 300px;
}

.chart--pie {
  height: 300px;
}

.chart--bar {
  height: 260px;
}

.dashboard__empty {
  color: var(--el-text-color-placeholder);
  font-size: 13px;
}

.ai-entry {
  position: fixed;
  right: 24px;
  bottom: 48px;
  z-index: 10;
}
</style>
