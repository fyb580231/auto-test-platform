<!--
  TaskList.vue —— 执行历史。

  职责：
  1. 顶部筛选：项目、状态、触发来源、关键字；
  2. 表格：任务编号（短）、名称、项目、环境、状态、用例数、通过/失败、通过率（进度条）、耗时、触发来源、开始时间、操作；
  3. running / pending 的任务自动轮询刷新（每 3 秒），全部结束即停止轮询；
  4. 「查看详情」抽屉内嵌 ReportViewer；支持通过 ?taskId=xx 直接打开某条任务报告；
  5. 支持重跑与删除。
-->
<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Delete, Refresh, Search, VideoPlay, View } from '@element-plus/icons-vue'

import { deleteTask, listTasks, retryTask } from '@/api/task'
import ReportViewer from '@/components/ReportViewer.vue'
import { useProjectStore } from '@/stores/project'
import type { Task, TaskStatus } from '@/types'
import {
  formatDateTime,
  formatDuration,
  shortTaskNo,
  taskStatusTagType,
  taskStatusText,
  triggerTypeTagType,
  triggerTypeText,
} from '@/utils/format'

/** 轮询间隔：存在未结束任务时每 3 秒刷新一次列表 */
const POLL_INTERVAL = 3000

const route = useRoute()
const router = useRouter()
const projectStore = useProjectStore()

/* -------------------------------- 列表状态 ------------------------------- */
const loading = ref(false)
const tasks = ref<Task[]>([])
const total = ref(0)

const query = reactive({
  status: '' as TaskStatus | '',
  triggerType: '',
  keyword: '',
  page: 1,
  size: 20,
})

const statusOptions: { value: TaskStatus | ''; label: string }[] = [
  { value: '', label: '全部状态' },
  { value: 'running', label: '执行中' },
  { value: 'pending', label: '等待中' },
  { value: 'success', label: '成功' },
  { value: 'failed', label: '失败' },
  { value: 'error', label: '执行异常' },
]

const triggerOptions: { value: string; label: string }[] = [
  { value: 'manual', label: '手工触发' },
  { value: 'suite', label: '用例集' },
  { value: 'schedule', label: '定时调度' },
  { value: 'retry', label: '重跑' },
]

/** 当前项目 ID */
const projectId = computed<number | null>(() => projectStore.currentProjectId)

/** 项目下拉切换 */
function handleProjectChange(value: unknown): void {
  if (value === undefined || value === null) return
  projectStore.setCurrentProject(Number(value))
}

/** 加载任务列表（silent 用于轮询，避免闪烁） */
async function loadTasks(silent = false): Promise<void> {
  if (!silent) loading.value = true
  try {
    const page = await listTasks({
      project_id: projectId.value,
      status: query.status,
      trigger_type: query.triggerType,
      keyword: query.keyword.trim(),
      page: query.page,
      size: query.size,
    })
    tasks.value = page.items
    total.value = page.total
  } catch {
    // 错误提示已由 axios 拦截器统一处理
  } finally {
    if (!silent) loading.value = false
  }
  syncPolling()
}

/** 条件变化后回到第一页 */
async function handleSearch(): Promise<void> {
  query.page = 1
  await loadTasks()
}

/** 重置筛选条件 */
async function handleReset(): Promise<void> {
  query.status = ''
  query.triggerType = ''
  query.keyword = ''
  query.page = 1
  await loadTasks()
}

/** 分页变化 */
async function handlePageChange(page: number): Promise<void> {
  query.page = page
  await loadTasks()
}

/** 每页条数变化 */
async function handleSizeChange(size: number): Promise<void> {
  query.size = size
  query.page = 1
  await loadTasks()
}

/* -------------------------------- 轮询控制 ------------------------------- */
let pollTimer: number | null = null

/** 是否存在未结束的任务 */
function hasActiveTask(): boolean {
  return tasks.value.some((item) => item.status === 'running' || item.status === 'pending')
}

/** 启动轮询 */
function startPolling(): void {
  if (pollTimer !== null) return
  pollTimer = window.setInterval(() => {
    void loadTasks(true)
    // 详情抽屉打开且任务仍在执行时，同步刷新报告
    if (detailVisible.value) void reportRef.value?.reload()
  }, POLL_INTERVAL)
}

/** 停止轮询 */
function stopPolling(): void {
  if (pollTimer === null) return
  window.clearInterval(pollTimer)
  pollTimer = null
}

/** 根据是否存在未结束任务开关轮询 */
function syncPolling(): void {
  if (hasActiveTask()) {
    startPolling()
  } else {
    stopPolling()
  }
}

/* -------------------------------- 详情抽屉 ------------------------------- */
const detailVisible = ref(false)
const detailTaskId = ref<number>(0)
const reportRef = ref<InstanceType<typeof ReportViewer> | null>(null)

/** 打开报告抽屉 */
function openDetail(row: Task): void {
  detailTaskId.value = row.id
  detailVisible.value = true
  void router.replace({ path: '/tasks', query: { taskId: String(row.id) } })
}

/* -------------------------------- 重跑 / 删除 ---------------------------- */
/** 重跑任务 */
async function handleRetry(row: Task): Promise<void> {
  try {
    const created = await retryTask(row.id)
    await promptGoTasks(created)
    await loadTasks()
  } catch {
    // 错误提示已由 axios 拦截器统一处理
  }
}

/** 任务创建成功后的提示：提供跳转执行历史的入口 */
async function promptGoTasks(task: Task): Promise<void> {
  try {
    await ElMessageBox.confirm(
      `重跑任务「${task.name}」已创建（${task.task_no}），当前状态：${taskStatusText(task.status)}。`,
      '任务已创建',
      { type: 'success', confirmButtonText: '查看执行历史', cancelButtonText: '留在当前页' },
    )
    await router.push({ path: '/tasks', query: { taskId: String(task.id) } })
  } catch {
    // 选择「留在当前页」时不跳转
  }
}

/** 删除任务记录 */
async function handleDelete(row: Task): Promise<void> {
  try {
    await ElMessageBox.confirm(`确认删除任务「${row.name}」（${row.task_no}）吗？`, '删除任务', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  try {
    const result = await deleteTask(row.id)
    ElMessage.success(result.message || '任务已删除')
    await loadTasks()
  } catch {
    // 错误提示已由 axios 拦截器统一处理
  }
}

/** 通过率进度条颜色 */
function passRateColor(rate: number): string {
  if (rate >= 90) return '#67c23a'
  if (rate >= 70) return '#e6a23c'
  return '#f56c6c'
}

onMounted(async () => {
  if (!projectStore.projects.length) await projectStore.loadProjects().catch(() => undefined)
  await loadTasks()

  // 支持从首页/用例页带 ?taskId= 直接打开报告
  const queryTaskId = Number(route.query.taskId)
  if (Number.isFinite(queryTaskId) && queryTaskId > 0) {
    detailTaskId.value = queryTaskId
    detailVisible.value = true
  }
})

onBeforeUnmount(() => {
  stopPolling()
})
</script>

<template>
  <div class="task-list">
    <el-card shadow="never" class="task-list__filter">
      <div class="task-list__filter-row">
        <el-select
          :model-value="projectId ?? undefined"
          placeholder="全部项目"
          clearable
          class="task-list__project"
          @change="handleProjectChange"
        >
          <el-option
            v-for="item in projectStore.projects"
            :key="item.id"
            :label="item.name"
            :value="item.id"
          />
        </el-select>

        <el-select v-model="query.status" class="task-list__status" @change="handleSearch">
          <el-option
            v-for="item in statusOptions"
            :key="String(item.value)"
            :label="item.label"
            :value="item.value"
          />
        </el-select>

        <el-select
          v-model="query.triggerType"
          placeholder="触发来源"
          clearable
          class="task-list__trigger"
          @change="handleSearch"
        >
          <el-option
            v-for="item in triggerOptions"
            :key="item.value"
            :label="item.label"
            :value="item.value"
          />
        </el-select>

        <el-input
          v-model="query.keyword"
          placeholder="搜索任务名称 / 编号"
          :prefix-icon="Search"
          clearable
          class="task-list__keyword"
          @keyup.enter="handleSearch"
          @clear="handleSearch"
        />

        <el-button type="primary" :icon="Search" @click="handleSearch">查询</el-button>
        <el-button :icon="Refresh" @click="handleReset">重置</el-button>
        <el-tag v-if="hasActiveTask()" size="small" type="primary" effect="plain">
          存在执行中的任务，列表每 3 秒自动刷新
        </el-tag>
      </div>
    </el-card>

    <el-card shadow="never">
      <el-table v-loading="loading" :data="tasks" row-key="id">
        <el-table-column label="任务编号" width="130">
          <template #default="{ row }">
            <span class="task-cell__no">{{ shortTaskNo(row.task_no) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="name" label="任务名称" min-width="200" show-overflow-tooltip />
        <el-table-column label="项目" width="140" show-overflow-tooltip>
          <template #default="{ row }">{{ row.project_name || '-' }}</template>
        </el-table-column>
        <el-table-column label="环境" width="130" show-overflow-tooltip>
          <template #default="{ row }">{{ row.environment_name || '默认环境' }}</template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="taskStatusTagType(row.status)" size="small" effect="light">
              {{ taskStatusText(row.status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="total" label="用例数" width="80" align="center" />
        <el-table-column label="通过 / 失败" width="110" align="center">
          <template #default="{ row }">
            <span class="text-success">{{ row.passed }}</span> /
            <span class="text-danger">{{ row.failed }}</span>
          </template>
        </el-table-column>
        <el-table-column label="通过率" width="170">
          <template #default="{ row }">
            <div class="task-cell__rate">
              <el-progress
                :percentage="Math.round(row.pass_rate)"
                :stroke-width="6"
                :show-text="false"
                :color="passRateColor(row.pass_rate)"
                class="task-cell__progress"
              />
              <span class="task-cell__rate-text">
                {{ row.total ? `${row.pass_rate.toFixed(1)}%` : '-' }}
              </span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="耗时" width="100">
          <template #default="{ row }">{{ formatDuration(row.duration_ms) }}</template>
        </el-table-column>
        <el-table-column label="触发来源" width="110">
          <template #default="{ row }">
            <el-tag :type="triggerTypeTagType(row.trigger_type)" size="small" effect="plain">
              {{ triggerTypeText(row.trigger_type) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="开始时间" width="170">
          <template #default="{ row }">{{ formatDateTime(row.started_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="210" fixed="right">
          <template #default="{ row }">
            <!-- el-table 插槽的 row 是宽松记录类型，这里断言成业务类型后传给处理函数 -->
            <el-button text type="primary" :icon="View" @click="openDetail(row as Task)">
              查看详情
            </el-button>
            <el-button text :icon="VideoPlay" @click="handleRetry(row as Task)">重跑</el-button>
            <el-button text type="danger" :icon="Delete" @click="handleDelete(row as Task)">
              删除
            </el-button>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="暂无执行记录" :image-size="90" />
        </template>
      </el-table>

      <el-pagination
        v-if="total > 0"
        class="task-list__pagination"
        :current-page="query.page"
        :page-size="query.size"
        :page-sizes="[10, 20, 50, 100]"
        :total="total"
        layout="total, sizes, prev, pager, next, jumper"
        background
        @current-change="handlePageChange"
        @size-change="handleSizeChange"
      />
    </el-card>

    <!-- 报告抽屉 -->
    <el-drawer v-model="detailVisible" title="执行报告" size="1080px" :destroy-on-close="true">
      <ReportViewer v-if="detailTaskId" ref="reportRef" :task-id="detailTaskId" />
    </el-drawer>
  </div>
</template>

<style scoped>
.task-list__filter {
  margin-bottom: 16px;
}

.task-list__filter-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}

.task-list__project {
  width: 200px;
}

.task-list__status {
  width: 140px;
}

.task-list__trigger {
  width: 140px;
}

.task-list__keyword {
  width: 220px;
}

.task-list__pagination {
  margin-top: 16px;
  justify-content: flex-end;
}

.task-cell__no {
  font-family: Consolas, Monaco, 'Courier New', monospace;
  font-size: 12px;
}

.task-cell__rate {
  display: flex;
  align-items: center;
  gap: 8px;
}

.task-cell__progress {
  flex: 1;
  min-width: 60px;
}

.task-cell__rate-text {
  font-size: 12px;
  color: var(--el-text-color-regular);
  width: 46px;
}

.text-success {
  color: var(--el-color-success);
}

.text-danger {
  color: var(--el-color-danger);
}
</style>
