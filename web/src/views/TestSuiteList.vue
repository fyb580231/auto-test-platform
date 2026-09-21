<!--
  TestSuiteList.vue —— 用例集管理。

  职责：
  1. 顶部展示调度器状态与已注册的定时任务（/api/scheduler/jobs）；
  2. 用例集列表：名称、用例数、环境、cron 表达式、失败重跑次数、启用开关、上次执行时间、操作；
  3. 新建 / 编辑抽屉：名称、描述、用例穿梭框（数据源为当前项目用例）、环境下拉、cron 表达式（5 段校验 + 示例）、
     失败重跑次数、启用开关；
  4. 操作列提供「执行」，创建任务后可跳转执行历史。
-->
<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from 'element-plus'
import { Delete, Edit, Plus, Refresh, Timer, VideoPlay } from '@element-plus/icons-vue'

import { listEnvironments } from '@/api/environment'
import { listCases } from '@/api/testcase'
import {
  createSuite,
  deleteSuite,
  getSchedulerJobs,
  listSuites,
  runSuite,
  updateSuite,
} from '@/api/testsuite'
import { useProjectStore } from '@/stores/project'
import type { Environment, SchedulerJob, TaskStatus, TestCase, TestSuite, TestSuitePayload } from '@/types'
import { formatDateTime, taskStatusText } from '@/utils/format'

const router = useRouter()
const projectStore = useProjectStore()

/** 当前项目 ID */
const projectId = computed<number | null>(() => projectStore.currentProjectId)

/* -------------------------------- 列表数据 ------------------------------- */
const loading = ref(false)
const suites = ref<TestSuite[]>([])
const environments = ref<Environment[]>([])
const cases = ref<TestCase[]>([])

/** 调度器状态 */
const schedulerRunning = ref(false)
const schedulerJobs = ref<SchedulerJob[]>([])
const schedulerLoading = ref(false)

/** 项目下拉切换 */
function handleProjectChange(value: unknown): void {
  if (value === undefined || value === null) return
  projectStore.setCurrentProject(Number(value))
}

/** 加载用例集列表 */
async function loadSuites(): Promise<void> {
  if (!projectId.value) {
    suites.value = []
    return
  }
  loading.value = true
  try {
    suites.value = await listSuites(projectId.value)
  } catch {
    // 错误提示已由 axios 拦截器统一处理
  } finally {
    loading.value = false
  }
}

/** 加载环境与用例（用于抽屉里的下拉与穿梭框） */
async function loadOptions(): Promise<void> {
  if (!projectId.value) {
    environments.value = []
    cases.value = []
    return
  }
  try {
    environments.value = await listEnvironments(projectId.value)
  } catch {
    environments.value = []
  }
  try {
    const page = await listCases(projectId.value, { size: 200 })
    cases.value = page.items
  } catch {
    cases.value = []
  }
}

/** 加载调度器状态 */
async function loadScheduler(): Promise<void> {
  schedulerLoading.value = true
  try {
    const result = await getSchedulerJobs()
    schedulerRunning.value = result.running
    schedulerJobs.value = result.jobs
  } catch {
    schedulerRunning.value = false
    schedulerJobs.value = []
  } finally {
    schedulerLoading.value = false
  }
}

/** 统一刷新 */
async function reloadAll(): Promise<void> {
  await Promise.all([loadSuites(), loadOptions(), loadScheduler()])
}

/* ------------------------------ 穿梭框数据源 ----------------------------- */
/** el-transfer 需要 { key, label } 结构 */
const transferData = computed(() => cases.value.map((item) => ({ key: item.id, label: item.name })))

/* ------------------------------- 抽屉表单 ------------------------------- */
const drawerVisible = ref(false)
const saving = ref(false)
const editingId = ref<number | null>(null)
const formRef = ref<FormInstance>()

const form = reactive({
  name: '',
  description: '',
  case_ids: [] as number[],
  environment_id: null as number | null,
  cron_expression: '',
  retry_times: 2,
  enabled: true,
})

const drawerTitle = computed(() => (editingId.value ? '编辑用例集' : '新建用例集'))

const rules: FormRules<typeof form> = {
  name: [{ required: true, message: '请输入用例集名称', trigger: 'blur' }],
}

/** cron 表达式示例 */
const cronExamples = [
  { value: '0 2 * * *', label: '每天 02:00' },
  { value: '0 */4 * * *', label: '每 4 小时' },
  { value: '30 9 * * 1-5', label: '工作日 09:30' },
]

/**
 * 校验 cron 表达式：后端要求标准 5 段，这里提前给出提示，避免提交后才报错。
 * 返回空字符串表示通过。
 */
function validateCron(value: string): string {
  const trimmed = value.trim()
  if (!trimmed) return ''
  if (trimmed.split(/\s+/).length !== 5) {
    return 'cron 表达式必须是 5 段（分 时 日 月 周），例如「0 2 * * *」表示每天 02:00'
  }
  if (!/^[\d*,\-/ ]+$/.test(trimmed)) {
    return 'cron 表达式只能包含数字、* 、, 、- 、/ 和空格'
  }
  return ''
}

/** 当前 cron 错误提示 */
const cronError = computed(() => validateCron(form.cron_expression))

/** 打开新建抽屉 */
function openCreate(): void {
  editingId.value = null
  form.name = ''
  form.description = ''
  form.case_ids = []
  form.environment_id = environments.value.find((item) => item.is_default)?.id ?? null
  form.cron_expression = ''
  form.retry_times = 2
  form.enabled = true
  drawerVisible.value = true
  void formRef.value?.clearValidate()
}

/** 打开编辑抽屉 */
function openEdit(row: TestSuite): void {
  editingId.value = row.id
  form.name = row.name
  form.description = row.description ?? ''
  form.case_ids = [...row.case_ids]
  form.environment_id = row.environment_id
  form.cron_expression = row.cron_expression ?? ''
  form.retry_times = row.retry_times
  form.enabled = row.enabled
  drawerVisible.value = true
  void formRef.value?.clearValidate()
}

/** 应用 cron 示例 */
function applyCronExample(value: string): void {
  form.cron_expression = value
}

/** 保存用例集 */
async function handleSave(): Promise<void> {
  if (!projectId.value) {
    ElMessage.warning('请先选择当前项目')
    return
  }
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return
  if (cronError.value) {
    ElMessage.error(cronError.value)
    return
  }
  if (!form.case_ids.length) {
    ElMessage.warning('请至少选择一条用例')
    return
  }

  const payload: TestSuitePayload = {
    name: form.name.trim(),
    description: form.description.trim() || null,
    case_ids: form.case_ids,
    environment_id: form.environment_id,
    cron_expression: form.cron_expression.trim() || null,
    retry_times: form.retry_times,
    enabled: form.enabled,
  }

  saving.value = true
  try {
    if (editingId.value) {
      await updateSuite(editingId.value, payload)
      ElMessage.success('用例集已更新')
    } else {
      await createSuite(projectId.value, payload)
      ElMessage.success('用例集已创建')
    }
    drawerVisible.value = false
    await reloadAll()
  } catch {
    // 错误提示已由 axios 拦截器统一处理
  } finally {
    saving.value = false
  }
}

/* -------------------------------- 启用开关 ------------------------------- */
/** 切换用例集启用状态 */
async function handleToggleEnabled(row: TestSuite): Promise<void> {
  try {
    await updateSuite(row.id, { enabled: row.enabled })
    ElMessage.success(row.enabled ? '用例集已启用' : '用例集已停用')
    await loadScheduler()
  } catch {
    row.enabled = !row.enabled
  }
}

/* -------------------------------- 执行用例集 ----------------------------- */
/** 执行整个用例集 */
async function handleRun(row: TestSuite): Promise<void> {
  try {
    const task = await runSuite(row.id, { environment_id: row.environment_id })
    await promptGoTasks(task.name, task.task_no, task.status, task.id)
    await loadSuites()
  } catch {
    // 错误提示已由 axios 拦截器统一处理
  }
}

/** 任务创建成功后引导跳转执行历史 */
async function promptGoTasks(
  name: string,
  taskNo: string,
  status: TaskStatus,
  taskId: number,
): Promise<void> {
  try {
    await ElMessageBox.confirm(
      `任务「${name}」已创建（${taskNo}），当前状态：${taskStatusText(status)}。执行结果可在「执行历史」查看。`,
      '任务已创建',
      { type: 'success', confirmButtonText: '查看执行历史', cancelButtonText: '留在当前页' },
    )
    await router.push({ path: '/tasks', query: { taskId: String(taskId) } })
  } catch {
    // 选择「留在当前页」时不跳转
  }
}

/* --------------------------------- 删除 --------------------------------- */
async function handleDelete(row: TestSuite): Promise<void> {
  try {
    await ElMessageBox.confirm(`确认删除用例集「${row.name}」吗？定时任务会同步移除。`, '删除用例集', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  try {
    const result = await deleteSuite(row.id)
    ElMessage.success(result.message || '用例集已删除')
    await reloadAll()
  } catch {
    // 错误提示已由 axios 拦截器统一处理
  }
}

/** 环境名称展示 */
function environmentName(environmentId: number | null): string {
  if (!environmentId) return '默认环境'
  return environments.value.find((item) => item.id === environmentId)?.name ?? `环境 ${environmentId}`
}

onMounted(async () => {
  if (!projectStore.projects.length) await projectStore.loadProjects().catch(() => undefined)
  await reloadAll()
})
</script>

<template>
  <div class="suite-list">
    <!-- 调度器状态 -->
    <el-card shadow="never" class="suite-list__scheduler">
      <template #header>
        <div class="suite-list__header">
          <span class="suite-list__header-title">
            <el-icon><Timer /></el-icon>
            调度器状态
            <el-tag :type="schedulerRunning ? 'success' : 'info'" size="small" effect="light">
              {{ schedulerRunning ? '运行中' : '未启动' }}
            </el-tag>
          </span>
          <el-button :icon="Refresh" size="small" @click="loadScheduler">刷新</el-button>
        </div>
      </template>
      <el-table v-loading="schedulerLoading" :data="schedulerJobs" size="small" border>
        <el-table-column prop="id" label="任务 ID" min-width="220" show-overflow-tooltip />
        <el-table-column prop="name" label="任务名称" min-width="200" show-overflow-tooltip />
        <el-table-column label="下次执行时间" width="180">
          <template #default="{ row }">{{ formatDateTime(row.next_run_time) }}</template>
        </el-table-column>
        <el-table-column prop="trigger" label="触发器" min-width="200" show-overflow-tooltip />
        <template #empty>
          <span class="suite-list__empty">暂无已注册的定时任务（在用例集里填写 cron 表达式后自动注册）</span>
        </template>
      </el-table>
    </el-card>

    <!-- 用例集列表 -->
    <el-card shadow="never">
      <div class="suite-list__toolbar">
        <div class="suite-list__toolbar-left">
          <span class="suite-list__label">当前项目</span>
          <el-select
            :model-value="projectId ?? undefined"
            placeholder="请选择项目"
            class="suite-list__project"
            @change="handleProjectChange"
          >
            <el-option
              v-for="item in projectStore.projects"
              :key="item.id"
              :label="item.name"
              :value="item.id"
            />
          </el-select>
        </div>
        <div class="suite-list__toolbar-right">
          <el-button :icon="Refresh" @click="reloadAll">刷新</el-button>
          <el-button type="primary" :icon="Plus" :disabled="!projectId" @click="openCreate">
            新建用例集
          </el-button>
        </div>
      </div>

      <el-table v-loading="loading" :data="suites" row-key="id">
        <el-table-column label="用例集名称" min-width="200" show-overflow-tooltip>
          <template #default="{ row }">
            <div class="suite-cell__name">{{ row.name }}</div>
            <div v-if="row.description" class="suite-cell__desc">{{ row.description }}</div>
          </template>
        </el-table-column>
        <el-table-column prop="case_count" label="用例数" width="90" align="center" />
        <el-table-column label="默认环境" width="140">
          <template #default="{ row }">{{ environmentName(row.environment_id) }}</template>
        </el-table-column>
        <el-table-column label="cron 表达式" width="140">
          <template #default="{ row }">
            <span v-if="row.cron_expression" class="suite-cell__cron">{{ row.cron_expression }}</span>
            <span v-else class="suite-cell__muted">未配置</span>
          </template>
        </el-table-column>
        <el-table-column prop="retry_times" label="重跑次数" width="100" align="center" />
        <el-table-column label="启用" width="80" align="center">
          <template #default="{ row }">
            <el-switch v-model="row.enabled" @change="handleToggleEnabled(row as TestSuite)" />
          </template>
        </el-table-column>
        <el-table-column label="上次执行" width="170">
          <template #default="{ row }">{{ formatDateTime(row.last_run_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="200" fixed="right">
          <template #default="{ row }">
            <!-- el-table 插槽的 row 是宽松记录类型，这里断言成业务类型后传给处理函数 -->
            <el-button text type="primary" :icon="VideoPlay" @click="handleRun(row as TestSuite)">
              执行
            </el-button>
            <el-button text :icon="Edit" @click="openEdit(row as TestSuite)">编辑</el-button>
            <el-button text type="danger" :icon="Delete" @click="handleDelete(row as TestSuite)">
              删除
            </el-button>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty
            :description="projectId ? '暂无用例集，点击右上角「新建用例集」' : '请先选择当前项目'"
            :image-size="90"
          />
        </template>
      </el-table>
    </el-card>

    <!-- 新建 / 编辑抽屉 -->
    <el-drawer v-model="drawerVisible" :title="drawerTitle" size="760px" :close-on-click-modal="false">
      <el-form ref="formRef" :model="form" :rules="rules" label-width="120px" @submit.prevent>
        <el-form-item label="用例集名称" prop="name">
          <el-input v-model="form.name" placeholder="例如：冒烟用例集" maxlength="255" />
        </el-form-item>

        <el-form-item label="描述">
          <el-input
            v-model="form.description"
            type="textarea"
            :rows="2"
            resize="none"
            maxlength="2000"
            placeholder="用例集用途说明"
          />
        </el-form-item>

        <el-form-item label="包含用例">
          <el-transfer
            v-model="form.case_ids"
            :data="transferData"
            filterable
            filter-placeholder="搜索用例名称"
            :titles="['待选用例', '已选用例']"
            class="suite-list__transfer"
          />
        </el-form-item>

        <el-form-item label="执行环境">
          <el-select
            v-model="form.environment_id"
            clearable
            placeholder="未指定时使用项目默认环境"
            class="suite-list__full"
          >
            <el-option
              v-for="item in environments"
              :key="item.id"
              :label="`${item.name}${item.is_default ? '（默认）' : ''}`"
              :value="item.id"
            />
          </el-select>
        </el-form-item>

        <el-form-item label="cron 表达式" :error="cronError">
          <div class="suite-list__cron-block">
            <el-input v-model="form.cron_expression" placeholder="如 0 2 * * *" />
            <div class="suite-list__cron-hint">
              <span>5 段格式：分 时 日 月 周，留空表示不定时执行。示例：</span>
              <el-button
                v-for="item in cronExamples"
                :key="item.value"
                size="small"
                text
                type="primary"
                @click="applyCronExample(item.value)"
              >
                {{ item.value }}（{{ item.label }}）
              </el-button>
            </div>
          </div>
        </el-form-item>

        <el-form-item label="失败重跑次数">
          <el-input-number v-model="form.retry_times" :min="0" :max="5" controls-position="right" />
          <span class="suite-list__hint">用例失败后自动重跑的次数，0 表示不重跑</span>
        </el-form-item>

        <el-form-item label="启用">
          <el-switch v-model="form.enabled" />
          <span class="suite-list__hint">停用后不会注册定时任务，但仍可手工执行</span>
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="drawerVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="handleSave">保存</el-button>
      </template>
    </el-drawer>
  </div>
</template>

<style scoped>
.suite-list__scheduler {
  margin-bottom: 16px;
}

.suite-list__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-weight: 600;
}

.suite-list__header-title {
  display: flex;
  align-items: center;
  gap: 8px;
}

.suite-list__empty {
  font-size: 12px;
  color: var(--el-text-color-placeholder);
}

.suite-list__toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px;
  margin-bottom: 16px;
}

.suite-list__toolbar-left {
  display: flex;
  align-items: center;
  gap: 10px;
}

.suite-list__toolbar-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.suite-list__label {
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.suite-list__project {
  width: 220px;
}

.suite-list__full {
  width: 100%;
}

.suite-list__transfer {
  width: 100%;
}

.suite-list__cron-block {
  width: 100%;
}

.suite-list__cron-hint {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: 6px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.suite-list__hint {
  margin-left: 10px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.suite-cell__name {
  font-weight: 600;
}

.suite-cell__desc {
  margin-top: 2px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.suite-cell__cron {
  font-family: Consolas, Monaco, 'Courier New', monospace;
}

.suite-cell__muted {
  color: var(--el-text-color-placeholder);
}
</style>
