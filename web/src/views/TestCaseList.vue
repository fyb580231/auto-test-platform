<!--
  TestCaseList.vue —— 用例管理（核心页面）。

  职责：
  1. 顶部筛选：项目、用例类型、标签、关键字；
  2. 表格：名称 / 类型 / 标签 / 方法+URL / 断言数 / 启用开关 / 更新时间 / 操作（编辑、执行、复制、删除）；
  3. 多选批量执行与单条执行：选择环境与失败重跑次数，创建任务后提供跳转执行历史的入口；
  4. AI 生成用例：填写接口信息 → 调 /ai/generate-cases → 勾选结果 → 导入（import 接口），并明确提示 Mock / 真实模型；
  5. 新建 / 编辑用例复用 CaseEditor 抽屉。
-->
<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from 'element-plus'
import {
  CopyDocument,
  Delete,
  Edit,
  MagicStick,
  Plus,
  Refresh,
  Search,
  VideoPlay,
} from '@element-plus/icons-vue'

import { generateCases, getAiStatus } from '@/api/ai'
import { listEnvironments } from '@/api/environment'
import {
  batchRunCases,
  createCase,
  deleteCase,
  importCases,
  listCases,
  runCase,
  updateCase,
} from '@/api/testcase'
import { listProjectTags } from '@/api/project'
import CaseEditor from '@/components/CaseEditor.vue'
import { useProjectStore } from '@/stores/project'
import type {
  AiStatus,
  CasePayload,
  CaseType,
  Environment,
  Task,
  TestCase,
} from '@/types'
import { formatDateTime, taskStatusText } from '@/utils/format'

const router = useRouter()
const projectStore = useProjectStore()

/* -------------------------------- 列表状态 ------------------------------- */
const loading = ref(false)
const cases = ref<TestCase[]>([])
const total = ref(0)
const tagOptions = ref<string[]>([])
const selectedCases = ref<TestCase[]>([])

const query = reactive({
  caseType: '' as CaseType | '',
  tag: '',
  keyword: '',
  page: 1,
  size: 20,
})

/** 当前项目 ID */
const projectId = computed<number | null>(() => projectStore.currentProjectId)

/** 项目下拉切换 */
function handleProjectChange(value: unknown): void {
  if (value === undefined || value === null) return
  projectStore.setCurrentProject(Number(value))
}

/** 加载用例列表 */
async function loadCases(): Promise<void> {
  if (!projectId.value) {
    cases.value = []
    total.value = 0
    return
  }
  loading.value = true
  try {
    const page = await listCases(projectId.value, {
      case_type: query.caseType,
      tag: query.tag,
      keyword: query.keyword.trim(),
      page: query.page,
      size: query.size,
    })
    cases.value = page.items
    total.value = page.total
  } catch {
    // 错误提示已由 axios 拦截器统一处理
  } finally {
    loading.value = false
  }
}

/** 加载标签候选 */
async function loadTags(): Promise<void> {
  if (!projectId.value) {
    tagOptions.value = []
    return
  }
  try {
    tagOptions.value = await listProjectTags(projectId.value)
  } catch {
    tagOptions.value = []
  }
}

/** 条件变化后回到第一页查询 */
async function handleSearch(): Promise<void> {
  query.page = 1
  await loadCases()
}

/** 重置筛选条件 */
async function handleReset(): Promise<void> {
  query.caseType = ''
  query.tag = ''
  query.keyword = ''
  query.page = 1
  await loadCases()
}

/** 分页参数变化 */
async function handlePageChange(page: number): Promise<void> {
  query.page = page
  await loadCases()
}

/** 每页条数变化 */
async function handleSizeChange(size: number): Promise<void> {
  query.size = size
  query.page = 1
  await loadCases()
}

/** 表格多选变化 */
function handleSelectionChange(rows: TestCase[]): void {
  selectedCases.value = rows
}

/* ------------------------------- 启用开关 ------------------------------- */
/** 切换用例启用状态 */
async function handleToggleEnabled(row: TestCase): Promise<void> {
  try {
    await updateCase(row.id, { enabled: row.enabled })
    ElMessage.success(row.enabled ? '用例已启用' : '用例已停用')
  } catch {
    // 失败时回滚开关状态，保持与后端一致
    row.enabled = !row.enabled
  }
}

/* ------------------------------ 新建 / 编辑 ------------------------------ */
const editorVisible = ref(false)
const editingCaseId = ref<number | null>(null)

/** 打开新建抽屉 */
function openCreate(): void {
  editingCaseId.value = null
  editorVisible.value = true
}

/** 打开编辑抽屉 */
function openEdit(row: TestCase): void {
  editingCaseId.value = row.id
  editorVisible.value = true
}

/** 用例保存成功后刷新列表与标签 */
async function handleSaved(): Promise<void> {
  await Promise.all([loadCases(), loadTags()])
}

/* -------------------------------- 复制用例 ------------------------------- */
/** 把一条用例的所有字段转成创建载荷 */
function toPayload(row: TestCase): CasePayload {
  return {
    name: row.name,
    case_type: row.case_type,
    description: row.description,
    tags: [...row.tags],
    method: row.method ?? 'GET',
    url: row.url ?? '',
    headers: { ...row.headers },
    params: { ...row.params },
    body: row.body,
    form: { ...row.form },
    setup_case_id: row.setup_case_id,
    extract: row.extract.map((rule) => ({ ...rule })),
    steps: row.steps.map((step) => ({ ...step })),
    assertions: row.assertions.map((rule) => ({ ...rule })),
    enabled: row.enabled,
  }
}

/** 复制用例（列表数据已包含全部字段，无需额外请求详情） */
async function handleDuplicate(row: TestCase): Promise<void> {
  if (!projectId.value) return
  try {
    const payload = toPayload(row)
    payload.name = `${row.name}（副本）`
    await createCase(projectId.value, payload)
    ElMessage.success('用例已复制')
    await handleSearch()
  } catch {
    // 错误提示已由 axios 拦截器统一处理
  }
}

/* --------------------------------- 删除 --------------------------------- */
async function handleDelete(row: TestCase): Promise<void> {
  try {
    await ElMessageBox.confirm(`确认删除用例「${row.name}」吗？删除后无法恢复。`, '删除用例', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  try {
    const result = await deleteCase(row.id)
    ElMessage.success(result.message || '用例已删除')
    await Promise.all([loadCases(), loadTags()])
  } catch {
    // 错误提示已由 axios 拦截器统一处理
  }
}

/* -------------------------------- 执行用例 ------------------------------- */
const environments = ref<Environment[]>([])
const runDialogVisible = ref(false)
const runSubmitting = ref(false)
const runMode = ref<'single' | 'batch'>('single')
const runTargetCase = ref<TestCase | null>(null)
const runEnvironmentId = ref<number | null>(null)
const runRetryTimes = ref(0)

/** 加载环境列表 */
async function loadEnvironments(): Promise<void> {
  if (!projectId.value) {
    environments.value = []
    return
  }
  try {
    environments.value = await listEnvironments(projectId.value)
    const defaultEnv = environments.value.find((item) => item.is_default)
    runEnvironmentId.value = defaultEnv ? defaultEnv.id : null
  } catch {
    environments.value = []
  }
}

/** 打开单条执行对话框 */
function openRunSingle(row: TestCase): void {
  runMode.value = 'single'
  runTargetCase.value = row
  runEnvironmentId.value = runEnvironmentId.value ?? null
  runDialogVisible.value = true
}

/** 打开批量执行对话框 */
function openRunBatch(): void {
  if (!selectedCases.value.length) {
    ElMessage.warning('请先勾选需要执行的用例')
    return
  }
  const disabledCount = selectedCases.value.filter((item) => !item.enabled).length
  if (disabledCount) {
    ElMessage.warning(`选中的用例中有 ${disabledCount} 条已停用，请先启用或取消勾选`)
    return
  }
  runMode.value = 'batch'
  runTargetCase.value = null
  runDialogVisible.value = true
}

/** 提交执行，创建任务后引导跳转执行历史 */
async function submitRun(): Promise<void> {
  runSubmitting.value = true
  try {
    let task: Task
    if (runMode.value === 'single' && runTargetCase.value) {
      task = await runCase(runTargetCase.value.id, runEnvironmentId.value)
    } else {
      task = await batchRunCases({
        case_ids: selectedCases.value.map((item) => item.id),
        environment_id: runEnvironmentId.value,
        retry_times: runRetryTimes.value,
      })
    }
    runDialogVisible.value = false
    await promptGoTasks(task)
  } catch {
    // 错误提示已由 axios 拦截器统一处理
  } finally {
    runSubmitting.value = false
  }
}

/** 任务创建成功后的提示：提供跳转执行历史的入口 */
async function promptGoTasks(task: Task): Promise<void> {
  try {
    await ElMessageBox.confirm(
      `任务「${task.name}」已创建（${task.task_no}），当前状态：${taskStatusText(task.status)}。执行结果可在「执行历史」查看。`,
      '任务已创建',
      {
        type: 'success',
        confirmButtonText: '查看执行历史',
        cancelButtonText: '留在当前页',
        distinguishCancelAndClose: true,
      },
    )
    await router.push({ path: '/tasks', query: { taskId: String(task.id) } })
  } catch {
    // 选择「留在当前页」时不跳转
  }
}

/* ------------------------------ AI 生成用例 ------------------------------ */
const aiDialogVisible = ref(false)
const aiFormRef = ref<FormInstance>()
const aiSubmitting = ref(false)
const aiImporting = ref(false)
const aiStatus = ref<AiStatus | null>(null)
const aiCases = ref<CasePayload[]>([])
const aiSelectedIndexes = ref<number[]>([])
const aiModelInfo = ref('')

const aiForm = reactive({
  url: '',
  method: 'GET',
  description: '',
  case_count: 6,
  tags: ['ai'] as string[],
  extra_requirements: '',
})

const aiRules: FormRules<typeof aiForm> = {
  url: [{ required: true, message: '请输入接口地址', trigger: 'blur' }],
  description: [{ required: true, message: '请输入业务描述', trigger: 'blur' }],
}

/** 打开 AI 生成对话框 */
async function openAiDialog(): Promise<void> {
  if (!projectId.value) {
    ElMessage.warning('请先在「项目管理」中选择当前项目')
    return
  }
  aiDialogVisible.value = true
  aiCases.value = []
  aiSelectedIndexes.value = []
  aiModelInfo.value = ''
  try {
    aiStatus.value = await getAiStatus()
  } catch {
    aiStatus.value = null
  }
}

/** 调用 AI 生成用例 */
async function submitAiGenerate(): Promise<void> {
  if (!aiFormRef.value) return
  const valid = await aiFormRef.value.validate().catch(() => false)
  if (!valid) return

  aiSubmitting.value = true
  try {
    const result = await generateCases({
      url: aiForm.url.trim(),
      method: aiForm.method,
      description: aiForm.description.trim(),
      case_count: aiForm.case_count,
      tags: aiForm.tags,
      extra_requirements: aiForm.extra_requirements.trim() || null,
    })
    aiCases.value = result.cases
    aiSelectedIndexes.value = result.cases.map((_item, index) => index)
    aiModelInfo.value = result.mocked
      ? `模型：${result.model || 'Mock'}（Mock 降级，结果为内置示例）`
      : `模型：${result.model || '未知'}`
    ElMessage.success(`已生成 ${result.cases.length} 条用例，请勾选后导入`)
  } catch {
    // 错误提示已由 axios 拦截器统一处理
  } finally {
    aiSubmitting.value = false
  }
}

/** 导入勾选的 AI 用例 */
async function importAiCases(): Promise<void> {
  if (!projectId.value) return
  const selected = aiSelectedIndexes.value
    .map((index) => aiCases.value[index])
    .filter((item): item is CasePayload => Boolean(item))
  if (!selected.length) {
    ElMessage.warning('请至少勾选一条用例')
    return
  }

  aiImporting.value = true
  try {
    const result = await importCases(projectId.value, { cases: selected, overwrite: false })
    ElMessage.success(result.message || '导入完成')
    aiDialogVisible.value = false
    await Promise.all([handleSearch(), loadTags()])
  } catch {
    // 错误提示已由 axios 拦截器统一处理
  } finally {
    aiImporting.value = false
  }
}

/* --------------------------------- 生命周期 ------------------------------ */
/** 当前项目变化时重新加载数据 */
async function reloadAll(): Promise<void> {
  query.page = 1
  await Promise.all([loadCases(), loadTags(), loadEnvironments()])
}

onMounted(async () => {
  if (!projectStore.projects.length) await projectStore.loadProjects().catch(() => undefined)
  await reloadAll()
})
</script>

<template>
  <div class="case-list">
    <el-card shadow="never" class="case-list__filter">
      <div class="case-list__filter-row">
        <el-select
          :model-value="projectId ?? undefined"
          placeholder="请选择项目"
          class="case-list__project"
          @change="handleProjectChange"
        >
          <el-option
            v-for="item in projectStore.projects"
            :key="item.id"
            :label="item.name"
            :value="item.id"
          />
        </el-select>

        <el-radio-group v-model="query.caseType" @change="handleSearch">
          <el-radio-button value="">全部</el-radio-button>
          <el-radio-button value="api">接口用例</el-radio-button>
          <el-radio-button value="ui">UI 用例</el-radio-button>
        </el-radio-group>

        <el-select
          v-model="query.tag"
          placeholder="标签"
          clearable
          class="case-list__tag"
          @change="handleSearch"
        >
          <el-option v-for="tag in tagOptions" :key="tag" :label="tag" :value="tag" />
        </el-select>

        <el-input
          v-model="query.keyword"
          placeholder="搜索名称 / URL / 描述"
          :prefix-icon="Search"
          clearable
          class="case-list__keyword"
          @keyup.enter="handleSearch"
          @clear="handleSearch"
        />

        <el-button type="primary" :icon="Search" @click="handleSearch">查询</el-button>
        <el-button :icon="Refresh" @click="handleReset">重置</el-button>
      </div>

      <div class="case-list__actions">
        <el-button type="primary" :icon="Plus" :disabled="!projectId" @click="openCreate">
          新建用例
        </el-button>
        <el-button :icon="VideoPlay" :disabled="!selectedCases.length" @click="openRunBatch">
          批量执行{{ selectedCases.length ? `（${selectedCases.length}）` : '' }}
        </el-button>
        <el-button :icon="MagicStick" :disabled="!projectId" @click="openAiDialog">
          AI 生成用例
        </el-button>
        <el-button :icon="Refresh" @click="reloadAll">刷新</el-button>
      </div>
    </el-card>

    <el-card shadow="never">
      <el-table
        v-loading="loading"
        :data="cases"
        row-key="id"
        @selection-change="handleSelectionChange"
      >
        <el-table-column type="selection" width="46" :selectable="(row: TestCase) => row.enabled" />
        <el-table-column label="用例名称" min-width="220" show-overflow-tooltip>
          <template #default="{ row }">
            <div class="case-cell">
              <span class="case-cell__name">{{ row.name }}</span>
              <el-tag v-if="!row.enabled" size="small" type="info" effect="plain">已停用</el-tag>
            </div>
            <div v-if="row.description" class="case-cell__desc">{{ row.description }}</div>
          </template>
        </el-table-column>
        <el-table-column label="类型" width="90">
          <template #default="{ row }">
            <el-tag :type="row.case_type === 'ui' ? 'warning' : 'primary'" size="small" effect="light">
              {{ row.case_type === 'ui' ? 'UI' : '接口' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="标签" min-width="150">
          <template #default="{ row }">
            <template v-if="row.tags.length">
              <el-tag v-for="tag in row.tags" :key="tag" size="small" effect="plain" class="case-cell__tag">
                {{ tag }}
              </el-tag>
            </template>
            <span v-else class="case-cell__muted">-</span>
          </template>
        </el-table-column>
        <el-table-column label="方法 / 地址" min-width="240" show-overflow-tooltip>
          <template #default="{ row }">
            <template v-if="row.case_type === 'api'">
              <el-tag size="small" effect="plain" class="case-cell__method">{{ row.method }}</el-tag>
              <span class="case-cell__url">{{ row.url || '-' }}</span>
            </template>
            <span v-else class="case-cell__url">站点：{{ row.url || '-' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="断言 / 步骤" width="120" align="center">
          <template #default="{ row }">
            <span v-if="row.case_type === 'api'">{{ row.assertions.length }} 条断言</span>
            <span v-else>{{ row.steps.length }} 步 / {{ row.assertions.length }} 断言</span>
          </template>
        </el-table-column>
        <el-table-column label="启用" width="80" align="center">
          <template #default="{ row }">
            <el-switch v-model="row.enabled" @change="handleToggleEnabled(row as TestCase)" />
          </template>
        </el-table-column>
        <el-table-column label="更新时间" width="170">
          <template #default="{ row }">{{ formatDateTime(row.updated_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="240" fixed="right">
          <template #default="{ row }">
            <!-- el-table 插槽的 row 是宽松记录类型，这里断言成业务类型后传给处理函数 -->
            <el-button text type="primary" :icon="Edit" @click="openEdit(row as TestCase)">
              编辑
            </el-button>
            <el-button text type="primary" :icon="VideoPlay" @click="openRunSingle(row as TestCase)">
              执行
            </el-button>
            <el-button text :icon="CopyDocument" @click="handleDuplicate(row as TestCase)">
              复制
            </el-button>
            <el-button text type="danger" :icon="Delete" @click="handleDelete(row as TestCase)">
              删除
            </el-button>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty
            :description="projectId ? '暂无用例，可新建或使用 AI 生成' : '请先选择当前项目'"
            :image-size="90"
          />
        </template>
      </el-table>

      <el-pagination
        v-if="total > 0"
        class="case-list__pagination"
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

    <!-- 执行用例对话框 -->
    <el-dialog v-model="runDialogVisible" title="执行用例" width="460px">
      <el-form label-width="120px">
        <el-form-item label="执行对象">
          <span v-if="runMode === 'batch'">已选中 {{ selectedCases.length }} 条用例</span>
          <span v-else>{{ runTargetCase?.name }}</span>
        </el-form-item>
        <el-form-item label="执行环境">
          <el-select
            v-model="runEnvironmentId"
            clearable
            placeholder="未指定时使用项目默认环境"
            class="case-list__full"
          >
            <el-option
              v-for="item in environments"
              :key="item.id"
              :label="`${item.name}${item.is_default ? '（默认）' : ''}`"
              :value="item.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item v-if="runMode === 'batch'" label="失败重跑次数">
          <el-input-number v-model="runRetryTimes" :min="0" :max="5" controls-position="right" />
          <span class="case-list__hint">仅批量执行时生效</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="runDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="runSubmitting" @click="submitRun">创建任务</el-button>
      </template>
    </el-dialog>

    <!-- AI 生成用例对话框 -->
    <el-dialog v-model="aiDialogVisible" title="AI 生成用例" width="880px" top="6vh">
      <el-alert
        v-if="aiStatus"
        :type="aiStatus.mocked ? 'warning' : 'success'"
        :closable="false"
        show-icon
        class="case-list__ai-status"
        :title="
          aiStatus.mocked
            ? '当前为 Mock 模式：未配置 DEEPSEEK_API_KEY，返回内置示例结果'
            : `已接入真实模型：${aiStatus.model}`
        "
      />

      <el-form ref="aiFormRef" :model="aiForm" :rules="aiRules" label-width="110px">
        <el-form-item label="接口地址" prop="url">
          <el-input v-model="aiForm.url" placeholder="如 /api/login（可写相对路径）" />
        </el-form-item>
        <el-form-item label="请求方法">
          <el-select v-model="aiForm.method" class="case-list__method">
            <el-option
              v-for="item in ['GET', 'POST', 'PUT', 'PATCH', 'DELETE']"
              :key="item"
              :label="item"
              :value="item"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="业务描述" prop="description">
          <el-input
            v-model="aiForm.description"
            type="textarea"
            :rows="3"
            resize="none"
            placeholder="例如：用户登录，账号密码正确返回 token；密码错误返回 401；连续失败 5 次锁定账号"
          />
        </el-form-item>
        <el-form-item label="生成条数">
          <el-input-number v-model="aiForm.case_count" :min="4" :max="12" controls-position="right" />
          <span class="case-list__hint">建议 4-12 条，条数越多生成耗时越长</span>
        </el-form-item>
        <el-form-item label="标签">
          <el-select
            v-model="aiForm.tags"
            multiple
            filterable
            allow-create
            default-first-option
            class="case-list__full"
            placeholder="生成用例默认带上的标签"
          >
            <el-option v-for="tag in tagOptions" :key="tag" :label="tag" :value="tag" />
          </el-select>
        </el-form-item>
        <el-form-item label="额外要求">
          <el-input
            v-model="aiForm.extra_requirements"
            type="textarea"
            :rows="2"
            resize="none"
            placeholder="例如：必须覆盖密码错误 5 次锁定场景"
          />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :icon="MagicStick" :loading="aiSubmitting" @click="submitAiGenerate">
            开始生成
          </el-button>
          <span v-if="aiModelInfo" class="case-list__hint">{{ aiModelInfo }}</span>
        </el-form-item>
      </el-form>

      <template v-if="aiCases.length">
        <el-divider content-position="left">生成结果（可勾选后导入，共 {{ aiCases.length }} 条）</el-divider>
        <el-checkbox-group v-model="aiSelectedIndexes" class="case-list__ai-list">
          <div v-for="(item, index) in aiCases" :key="index" class="ai-case">
            <el-checkbox :value="index" />
            <div class="ai-case__body">
              <div class="ai-case__title">{{ item.name }}</div>
              <div class="ai-case__meta">
                <el-tag size="small" effect="plain">{{ item.method }}</el-tag>
                <span class="ai-case__url">{{ item.url }}</span>
              </div>
              <div class="ai-case__meta">
                断言 {{ item.assertions.length }} 条
                <template v-if="item.tags.length"> · 标签 {{ item.tags.join('、') }}</template>
                <template v-if="item.description"> · {{ item.description }}</template>
              </div>
            </div>
          </div>
        </el-checkbox-group>
      </template>

      <template #footer>
        <el-button @click="aiDialogVisible = false">取消</el-button>
        <el-button
          type="primary"
          :disabled="!aiCases.length"
          :loading="aiImporting"
          @click="importAiCases"
        >
          导入到用例列表（已选 {{ aiSelectedIndexes.length }} 条）
        </el-button>
      </template>
    </el-dialog>

    <!-- 用例编辑抽屉 -->
    <CaseEditor
      v-model="editorVisible"
      :project-id="projectId"
      :case-id="editingCaseId"
      @saved="handleSaved"
    />
  </div>
</template>

<style scoped>
.case-list__filter {
  margin-bottom: 16px;
}

.case-list__filter-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}

.case-list__actions {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px dashed var(--el-border-color-lighter);
}

.case-list__project {
  width: 200px;
}

.case-list__tag {
  width: 140px;
}

.case-list__keyword {
  width: 220px;
}

.case-list__pagination {
  margin-top: 16px;
  justify-content: flex-end;
}

.case-list__full {
  width: 100%;
}

.case-list__method {
  width: 140px;
}

.case-list__hint {
  margin-left: 10px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.case-list__ai-status {
  margin-bottom: 16px;
}

.case-list__ai-list {
  display: block;
  max-height: 320px;
  overflow-y: auto;
}

.case-cell__name {
  font-weight: 600;
}

.case-cell__desc {
  margin-top: 2px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.case-cell__tag {
  margin-right: 4px;
}

.case-cell__method {
  margin-right: 6px;
}

.case-cell__url {
  font-family: Consolas, Monaco, 'Courier New', monospace;
  font-size: 12px;
}

.case-cell__muted {
  color: var(--el-text-color-placeholder);
}

.ai-case {
  display: flex;
  gap: 8px;
  padding: 8px 0;
  border-bottom: 1px solid var(--el-border-color-lighter);
}

.ai-case__body {
  flex: 1;
  min-width: 0;
}

.ai-case__title {
  font-size: 13px;
  font-weight: 600;
}

.ai-case__meta {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 4px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.ai-case__url {
  font-family: Consolas, Monaco, 'Courier New', monospace;
  word-break: break-all;
}
</style>
