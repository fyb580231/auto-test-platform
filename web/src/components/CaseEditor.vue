<!--
  CaseEditor.vue —— 用例编辑抽屉（接口用例 / UI 用例共用）。

  职责（props: modelValue / projectId / caseId, emits: update:modelValue / saved）：
  1. 基本信息：名称、类型（api / ui，切换后表单联动）、描述、标签；
  2. 接口用例区：方法、URL（支持相对路径，执行时拼接环境 base_url）、Headers / Query / Body / Form（JSON 校验）、前置用例与变量提取规则；
  3. UI 用例区：站点地址 + 步骤编排表格（可增删、可上下移动，动作下拉带中文说明，open 动作的 URL 填在「值」列）；
  4. 断言区：表格化编辑，类型联动列可用性，并提供常用断言快速模板；
  5. JSON 字段非法时禁止提交，并给出明确的字段级错误提示。
-->
<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { Bottom, Delete, Plus, Top } from '@element-plus/icons-vue'

import { listProjectTags } from '@/api/project'
import { createCase, getCase, listCases, updateCase } from '@/api/testcase'
import type {
  AssertOp,
  AssertType,
  AssertionRule,
  CasePayload,
  CaseType,
  ExtractRule,
  JsonObject,
  JsonValue,
  TestCase,
  UiAction,
  UiStep,
} from '@/types'

const props = defineProps<{
  /** 抽屉显隐 */
  modelValue: boolean
  /** 所属项目（创建用例必填） */
  projectId: number | null
  /** 编辑的用例 ID；为空表示新建 */
  caseId: number | null
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: boolean): void
  (e: 'saved'): void
}>()

const visible = computed<boolean>({
  get: () => props.modelValue,
  set: (value: boolean) => emit('update:modelValue', value),
})

/** 编辑态标题：新建 / 编辑 */
const drawerTitle = computed(() => (props.caseId ? '编辑用例' : '新建用例'))

/* --------------------------------- 选项 --------------------------------- */
const methodOptions = ['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS']

/** UI 动作下拉：带中文说明，降低编排门槛 */
const uiActionOptions: { value: UiAction; label: string }[] = [
  { value: 'open', label: 'open=打开页面' },
  { value: 'click', label: 'click=点击' },
  { value: 'input', label: 'input=输入文本' },
  { value: 'assert_visible', label: 'assert_visible=断言元素可见' },
  { value: 'assert_text', label: 'assert_text=断言文本包含' },
  { value: 'assert_url', label: 'assert_url=断言当前URL匹配' },
  { value: 'assert_value', label: 'assert_value=断言输入框的值' },
  { value: 'wait', label: 'wait=等待（毫秒）' },
  { value: 'select', label: 'select=下拉框选择' },
  { value: 'hover', label: 'hover=鼠标悬停' },
  { value: 'press', label: 'press=键盘按键' },
  { value: 'screenshot', label: 'screenshot=截图' },
]

/** 断言类型下拉 */
const assertTypeOptions: { value: AssertType; label: string }[] = [
  { value: 'status_code', label: 'status_code=HTTP 状态码' },
  { value: 'json_field', label: 'json_field=JSON 字段' },
  { value: 'response_time', label: 'response_time=响应时间' },
  { value: 'schema', label: 'schema=JSON Schema' },
  { value: 'header', label: 'header=响应头' },
]

/** 断言操作符下拉 */
const assertOpOptions: { value: AssertOp; label: string }[] = [
  { value: 'eq', label: 'eq=等于' },
  { value: 'ne', label: 'ne=不等于' },
  { value: 'contains', label: 'contains=包含' },
  { value: 'not_contains', label: 'not_contains=不包含' },
  { value: 'gt', label: 'gt=大于' },
  { value: 'lt', label: 'lt=小于' },
  { value: 'ge', label: 'ge=大于等于' },
  { value: 'le', label: 'le=小于等于' },
  { value: 'empty', label: 'empty=为空' },
  { value: 'not_empty', label: 'not_empty=不为空' },
  { value: 'in', label: 'in=在集合中' },
  { value: 'regex', label: 'regex=正则匹配' },
  { value: 'length_eq', label: 'length_eq=长度等于' },
]

/** 内置标签候选（仍支持输入自定义标签） */
const defaultTagOptions = ['smoke', 'regression', 'critical']

/* --------------------------------- 状态 --------------------------------- */
const formRef = ref<FormInstance>()
const loading = ref(false)
const saving = ref(false)
const submitting = ref(false)

const tagOptions = ref<string[]>([...defaultTagOptions])
/** 同项目其它用例（前置用例候选） */
const setupCaseOptions = ref<TestCase[]>([])

const form = reactive({
  name: '',
  case_type: 'api' as CaseType,
  description: '',
  tags: [] as string[],
  method: 'GET',
  url: '',
  setup_case_id: null as number | null,
  enabled: true,
})

/** JSON 字段：以字符串形式编辑，提交前解析并校验 */
type JsonFieldKey = 'headers' | 'params' | 'body' | 'form'

const JSON_FIELD_LABELS: Record<JsonFieldKey, string> = {
  headers: '请求头 Headers',
  params: 'Query 参数',
  body: '请求体 Body',
  form: '表单 Form',
}

const jsonKeys: JsonFieldKey[] = ['headers', 'params', 'body', 'form']

const jsonTexts = reactive<Record<JsonFieldKey, string>>({
  headers: '{}',
  params: '{}',
  body: '',
  form: '{}',
})

const jsonErrors = reactive<Record<JsonFieldKey, string>>({
  headers: '',
  params: '',
  body: '',
  form: '',
})

/** 变量提取规则（配合前置用例使用） */
const extractRules = ref<ExtractRule[]>([])
/** UI 步骤 */
const steps = ref<UiStep[]>([])
/** 断言规则 */
const assertions = ref<AssertionRule[]>([])

const rules: FormRules<typeof form> = {
  name: [{ required: true, message: '请输入用例名称', trigger: 'blur' }],
  url: [
    {
      validator: (_rule, value: string, callback: (error?: Error) => void) => {
        if (form.case_type === 'api' && !value) {
          callback(new Error('接口用例需要填写 URL（可写相对路径）'))
          return
        }
        callback()
      },
      trigger: 'blur',
    },
  ],
}

/* ------------------------------ JSON 校验 ------------------------------ */
/** 校验单个 JSON 字段，返回是否合法 */
function validateJsonField(key: JsonFieldKey): boolean {
  const text = jsonTexts[key].trim()
  if (!text) {
    jsonErrors[key] = ''
    return true
  }
  try {
    const parsed: unknown = JSON.parse(text)
    if (key !== 'body' && (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed))) {
      jsonErrors[key] = `${JSON_FIELD_LABELS[key]} 必须是 JSON 对象，例如 {"key": "value"}`
      return false
    }
    jsonErrors[key] = ''
    return true
  } catch (error) {
    const reason = error instanceof Error ? error.message : '无法解析'
    jsonErrors[key] = `${JSON_FIELD_LABELS[key]} 不是合法 JSON：${reason}`
    return false
  }
}

/** 校验全部 JSON 字段（不短路，保证每个字段的错误都能展示出来） */
function validateAllJson(): boolean {
  const results = jsonKeys.map((key) => validateJsonField(key))
  return results.every(Boolean)
}

/** 解析 JSON 字段，非法或为空时返回兜底值 */
function parseJsonField(key: JsonFieldKey, fallback: JsonValue): JsonValue {
  const text = jsonTexts[key].trim()
  if (!text) return fallback
  try {
    return JSON.parse(text) as JsonValue
  } catch {
    return fallback
  }
}

/** 解析 JSON 对象字段 */
function parseJsonObjectField(key: JsonFieldKey): JsonObject {
  const parsed = parseJsonField(key, {})
  return typeof parsed === 'object' && parsed !== null && !Array.isArray(parsed)
    ? (parsed as JsonObject)
    : {}
}

/* ------------------------------ 断言列联动 ------------------------------ */
/** 根据断言类型决定某列是否可用 */
function assertFieldEnabled(type: AssertType): boolean {
  return type === 'json_field' || type === 'header'
}

/** 根据断言类型决定操作符是否可用（状态码固定等于、响应时间与 Schema 直接比期望值） */
function assertOpEnabled(type: AssertType): boolean {
  return type === 'json_field' || type === 'header'
}

/** 期望值输入框占位提示 */
function assertExpectedPlaceholder(type: AssertType): string {
  if (type === 'status_code') return '如 200'
  if (type === 'response_time') return '毫秒数，如 1000'
  if (type === 'schema') return 'JSON Schema 字符串，如 {"type":"object"}'
  return '期望值'
}

/** 切换断言类型时重置不适用字段，避免残留脏数据 */
function handleAssertTypeChange(row: AssertionRule): void {
  if (!assertFieldEnabled(row.type)) {
    row.field = null
  }
  if (!assertOpEnabled(row.type)) {
    row.op = row.type === 'response_time' ? 'lt' : 'eq'
  }
  if (row.type === 'response_time') {
    row.op = 'lt'
  }
}

/** 添加一条空断言 */
function addAssertion(): void {
  assertions.value.push({ type: 'status_code', op: 'eq', expected: 200, field: null, message: '', name: '' })
}

/** 断言快速模板 */
function applyAssertTemplate(template: 'status200' | 'businessCode' | 'responseTime'): void {
  if (template === 'status200') {
    assertions.value.push({
      type: 'status_code',
      op: 'eq',
      expected: 200,
      field: null,
      name: '状态码 200',
      message: 'HTTP 状态码应为 200',
    })
  } else if (template === 'businessCode') {
    assertions.value.push({
      type: 'json_field',
      op: 'eq',
      expected: 0,
      field: '$.code',
      name: '业务码为 0',
      message: '业务返回码应为 0',
    })
  } else {
    assertions.value.push({
      type: 'response_time',
      op: 'lt',
      expected: 1000,
      field: null,
      name: '响应时间小于 1s',
      message: '响应时间应小于 1000ms',
    })
  }
}

/* -------------------------------- UI 步骤 ------------------------------- */
/** 添加一个 UI 步骤 */
function addStep(): void {
  steps.value.push({
    action: 'open',
    selector: '',
    // open 动作的 URL 填在 value 里，默认带上「站点地址」，减少重复输入
    value: form.url,
    timeout: 15000,
    name: '',
  })
}

/** 删除指定步骤 */
function removeStep(index: number): void {
  steps.value.splice(index, 1)
}

/** 上移步骤 */
function moveStepUp(index: number): void {
  if (index <= 0) return
  const list = steps.value
  const current = list[index]
  const previous = list[index - 1]
  if (!current || !previous) return
  list[index - 1] = current
  list[index] = previous
}

/** 下移步骤 */
function moveStepDown(index: number): void {
  const list = steps.value
  if (index >= list.length - 1) return
  const current = list[index]
  const next = list[index + 1]
  if (!current || !next) return
  list[index + 1] = current
  list[index] = next
}

/** 动作变化后的联动提示（open 需要值 = URL，assert_url 的值 = 期望 URL） */
function handleStepActionChange(row: UiStep): void {
  if (row.action === 'open' && !row.value) {
    row.value = form.url
  }
}

/* ------------------------------- 变量提取 ------------------------------- */
/**
 * 提取变量的引用写法示例。
 * 写成常量而不是直接写在模板里，是因为模板插值里出现双花括号会被 Vue 当成插值结束符。
 */
const TOKEN_REFERENCE_EXAMPLE = '{{token}}'

/** 添加一条变量提取规则 */
function addExtractRule(): void {
  extractRules.value.push({ name: '', path: '$.data.' })
}

/** 删除一条变量提取规则 */
function removeExtractRule(index: number): void {
  extractRules.value.splice(index, 1)
}

/* ------------------------------ 数据装载 ------------------------------ */
/** 重置为「新建」状态 */
function resetForm(): void {
  form.name = ''
  form.case_type = 'api'
  form.description = ''
  form.tags = []
  form.method = 'GET'
  form.url = ''
  form.setup_case_id = null
  form.enabled = true
  jsonTexts.headers = '{}'
  jsonTexts.params = '{}'
  jsonTexts.body = ''
  jsonTexts.form = '{}'
  jsonKeys.forEach((key) => {
    jsonErrors[key] = ''
  })
  extractRules.value = []
  steps.value = []
  assertions.value = []
  formRef.value?.clearValidate()
}

/** 用详情数据填充表单 */
function fillForm(detail: TestCase): void {
  form.name = detail.name
  form.case_type = detail.case_type
  form.description = detail.description ?? ''
  form.tags = [...detail.tags]
  form.method = detail.method ?? 'GET'
  form.url = detail.url ?? ''
  form.setup_case_id = detail.setup_case_id
  form.enabled = detail.enabled
  jsonTexts.headers = JSON.stringify(detail.headers ?? {}, null, 2)
  jsonTexts.params = JSON.stringify(detail.params ?? {}, null, 2)
  jsonTexts.body = detail.body === null || detail.body === undefined ? '' : JSON.stringify(detail.body, null, 2)
  jsonTexts.form = JSON.stringify(detail.form ?? {}, null, 2)
  jsonKeys.forEach((key) => {
    jsonErrors[key] = ''
  })
  extractRules.value = detail.extract.map((rule) => ({ ...rule }))
  steps.value = detail.steps.map((step) => ({ ...step }))
  assertions.value = detail.assertions.map((rule) => ({ ...rule }))
  formRef.value?.clearValidate()
}

/** 加载项目标签与前置用例候选 */
async function loadOptions(): Promise<void> {
  if (!props.projectId) return
  try {
    const tags = await listProjectTags(props.projectId)
    tagOptions.value = Array.from(new Set([...defaultTagOptions, ...tags]))
  } catch {
    tagOptions.value = [...defaultTagOptions]
  }
  try {
    const page = await listCases(props.projectId, { size: 200 })
    setupCaseOptions.value = page.items.filter((item) => item.id !== props.caseId)
  } catch {
    setupCaseOptions.value = []
  }
}

/** 打开抽屉时装载数据 */
async function loadCase(): Promise<void> {
  if (!props.caseId) {
    resetForm()
    return
  }
  loading.value = true
  try {
    fillForm(await getCase(props.caseId))
  } catch {
    // 错误提示已由 axios 拦截器统一处理
  } finally {
    loading.value = false
  }
}

/* --------------------------------- 保存 --------------------------------- */
/** 构造提交载荷 */
function buildPayload(): CasePayload {
  return {
    name: form.name.trim(),
    case_type: form.case_type,
    description: form.description.trim() || null,
    tags: form.tags,
    method: form.method,
    url: form.url.trim(),
    headers: parseJsonObjectField('headers'),
    params: parseJsonObjectField('params'),
    body: form.case_type === 'api' ? parseJsonField('body', null) : null,
    form: parseJsonObjectField('form'),
    setup_case_id: form.case_type === 'api' ? form.setup_case_id : null,
    extract: form.case_type === 'api' ? extractRules.value.filter((rule) => rule.name.trim()) : [],
    steps: form.case_type === 'ui' ? steps.value : [],
    assertions: assertions.value,
    enabled: form.enabled,
  }
}

/** 保存用例 */
async function handleSave(): Promise<void> {
  if (!props.projectId) {
    ElMessage.warning('请先在「项目管理」中选择当前项目')
    return
  }
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return

  if (!validateAllJson()) {
    ElMessage.error('存在 JSON 格式错误，请修正后再保存')
    return
  }
  if (form.case_type === 'ui' && !steps.value.length) {
    ElMessage.warning('UI 用例至少需要一个步骤（第一步通常是 open=打开页面）')
    return
  }
  const invalidExtract = extractRules.value.find((rule) => !rule.name.trim() || !rule.path.trim())
  if (form.case_type === 'api' && invalidExtract) {
    ElMessage.warning('变量提取规则需要同时填写「变量名」与「JSON 路径」')
    return
  }

  saving.value = true
  submitting.value = true
  try {
    const payload = buildPayload()
    if (props.caseId) {
      await updateCase(props.caseId, payload)
      ElMessage.success('用例已更新')
    } else {
      await createCase(props.projectId, payload)
      ElMessage.success('用例已创建')
    }
    emit('saved')
    visible.value = false
  } catch {
    // 错误提示已由 axios 拦截器统一处理
  } finally {
    saving.value = false
    submitting.value = false
  }
}

/** 取消并关闭抽屉 */
function handleCancel(): void {
  visible.value = false
}

watch(
  () => props.modelValue,
  (opened) => {
    if (!opened) return
    void loadCase()
    void loadOptions()
  },
)
</script>

<template>
  <el-drawer v-model="visible" :title="drawerTitle" size="880px" :close-on-click-modal="false">
    <div v-loading="loading" class="case-editor">
      <el-form ref="formRef" :model="form" :rules="rules" label-width="110px" @submit.prevent>
        <el-divider content-position="left">基本信息</el-divider>

        <el-form-item label="用例名称" prop="name">
          <el-input v-model="form.name" placeholder="例如：登录成功返回 token" maxlength="255" show-word-limit />
        </el-form-item>

        <el-form-item label="用例类型">
          <el-radio-group v-model="form.case_type" :disabled="Boolean(props.caseId)">
            <el-radio-button value="api">接口用例</el-radio-button>
            <el-radio-button value="ui">UI 用例</el-radio-button>
          </el-radio-group>
          <span class="case-editor__hint">
            类型决定下方编辑区：接口用例配置请求与断言，UI 用例编排浏览器步骤。
          </span>
        </el-form-item>

        <el-form-item label="标签">
          <el-select
            v-model="form.tags"
            multiple
            filterable
            allow-create
            default-first-option
            placeholder="选择或输入标签后回车"
            class="case-editor__full"
          >
            <el-option v-for="tag in tagOptions" :key="tag" :label="tag" :value="tag" />
          </el-select>
        </el-form-item>

        <el-form-item label="描述">
          <el-input
            v-model="form.description"
            type="textarea"
            :rows="2"
            resize="none"
            placeholder="用例的校验点、前置条件等"
            maxlength="2000"
          />
        </el-form-item>

        <el-form-item label="启用">
          <el-switch v-model="form.enabled" />
          <span class="case-editor__hint">停用后不会参与批量执行与定时调度</span>
        </el-form-item>

        <!-- 接口用例 -->
        <template v-if="form.case_type === 'api'">
          <el-divider content-position="left">接口配置</el-divider>

          <el-form-item label="请求方法">
            <el-select v-model="form.method" class="case-editor__method">
              <el-option v-for="item in methodOptions" :key="item" :label="item" :value="item" />
            </el-select>
          </el-form-item>

          <el-form-item label="URL" prop="url">
            <el-input v-model="form.url" placeholder="如 /api/login（相对路径会拼接环境的 base_url）" />
          </el-form-item>

          <el-form-item label="前置用例">
            <el-select
              v-model="form.setup_case_id"
              clearable
              filterable
              placeholder="可选：先执行另一条用例，例如登录获取 token"
              class="case-editor__full"
            >
              <el-option
                v-for="item in setupCaseOptions"
                :key="item.id"
                :label="`${item.name}（${item.case_type === 'ui' ? 'UI' : '接口'}）`"
                :value="item.id"
              />
            </el-select>
          </el-form-item>

          <el-form-item v-if="form.setup_case_id" label="变量提取">
            <div class="case-editor__block">
              <el-table :data="extractRules" size="small" border>
                <el-table-column label="变量名" min-width="160">
                  <template #default="{ row }">
                    <el-input v-model="row.name" size="small" placeholder="如 token" />
                  </template>
                </el-table-column>
                <el-table-column label="JSON 路径" min-width="220">
                  <template #default="{ row }">
                    <el-input v-model="row.path" size="small" placeholder="如 $.data.token" />
                  </template>
                </el-table-column>
                <el-table-column label="操作" width="80" align="center">
                  <template #default="{ $index }">
                    <el-button text type="danger" :icon="Delete" @click="removeExtractRule($index)" />
                  </template>
                </el-table-column>
                <template #empty>
                  <span class="case-editor__empty">
                    立即登录：变量名 token、路径 $.data.token，主用例里用
                    {{ TOKEN_REFERENCE_EXAMPLE }} 引用
                  </span>
                </template>
              </el-table>
              <el-button size="small" :icon="Plus" class="case-editor__add" @click="addExtractRule">
                添加提取规则
              </el-button>
            </div>
          </el-form-item>

          <el-divider content-position="left">请求内容（JSON 格式）</el-divider>

          <el-form-item label="Headers" :error="jsonErrors.headers">
            <el-input
              v-model="jsonTexts.headers"
              type="textarea"
              :rows="4"
              resize="vertical"
              spellcheck="false"
              placeholder='{"Content-Type": "application/json"}'
              @input="validateJsonField('headers')"
            />
          </el-form-item>

          <el-form-item label="Query 参数" :error="jsonErrors.params">
            <el-input
              v-model="jsonTexts.params"
              type="textarea"
              :rows="3"
              resize="vertical"
              spellcheck="false"
              placeholder='{"page": 1}'
              @input="validateJsonField('params')"
            />
          </el-form-item>

          <el-form-item label="Body" :error="jsonErrors.body">
            <el-input
              v-model="jsonTexts.body"
              type="textarea"
              :rows="5"
              resize="vertical"
              spellcheck="false"
              placeholder='{"username": "{{username}}", "password": "{{password}}"}'
              @input="validateJsonField('body')"
            />
          </el-form-item>

          <el-form-item label="Form 表单" :error="jsonErrors.form">
            <el-input
              v-model="jsonTexts.form"
              type="textarea"
              :rows="3"
              resize="vertical"
              spellcheck="false"
              placeholder='{"grant_type": "password"}'
              @input="validateJsonField('form')"
            />
          </el-form-item>
        </template>

        <!-- UI 用例 -->
        <template v-else>
          <el-divider content-position="left">UI 步骤编排</el-divider>

          <el-form-item label="站点地址" prop="url">
            <el-input v-model="form.url" placeholder="如 https://www.saucedemo.com（open 步骤默认使用该地址）" />
          </el-form-item>

          <el-form-item label="步骤">
            <div class="case-editor__block">
              <el-table :data="steps" size="small" border>
                <el-table-column label="#" type="index" width="46" align="center" />
                <el-table-column label="动作" width="190">
                  <template #default="{ row }">
                    <el-select
                      v-model="row.action"
                      size="small"
                      @change="handleStepActionChange(row as UiStep)"
                    >
                      <el-option
                        v-for="item in uiActionOptions"
                        :key="item.value"
                        :label="item.label"
                        :value="item.value"
                      />
                    </el-select>
                  </template>
                </el-table-column>
                <el-table-column label="选择器" min-width="170">
                  <template #default="{ row }">
                    <el-input v-model="row.selector" size="small" placeholder="如 #login-button" />
                  </template>
                </el-table-column>
                <el-table-column label="值" min-width="180">
                  <template #default="{ row }">
                    <el-input
                      v-model="row.value"
                      size="small"
                      :placeholder="row.action === 'open' ? 'URL（open 动作填这里）' : '输入值 / 期望值'"
                    />
                  </template>
                </el-table-column>
                <el-table-column label="超时(ms)" width="110">
                  <template #default="{ row }">
                    <el-input-number
                      v-model="row.timeout"
                      size="small"
                      :min="1000"
                      :max="120000"
                      :step="1000"
                      controls-position="right"
                    />
                  </template>
                </el-table-column>
                <el-table-column label="备注" min-width="130">
                  <template #default="{ row }">
                    <el-input v-model="row.name" size="small" placeholder="可选" />
                  </template>
                </el-table-column>
                <el-table-column label="操作" width="130" align="center">
                  <template #default="{ $index }">
                    <el-button text :icon="Top" :disabled="$index === 0" @click="moveStepUp($index)" />
                    <el-button
                      text
                      :icon="Bottom"
                      :disabled="$index === steps.length - 1"
                      @click="moveStepDown($index)"
                    />
                    <el-button text type="danger" :icon="Delete" @click="removeStep($index)" />
                  </template>
                </el-table-column>
                <template #empty>
                  <span class="case-editor__empty">还没有步骤，建议第一步为 open=打开页面</span>
                </template>
              </el-table>
              <el-button size="small" :icon="Plus" class="case-editor__add" @click="addStep">
                添加步骤
              </el-button>
            </div>
          </el-form-item>
        </template>

        <!-- 断言 -->
        <el-divider content-position="left">断言规则</el-divider>

        <el-form-item label="断言">
          <div class="case-editor__block">
            <div class="case-editor__templates">
              <span class="case-editor__hint">快速模板：</span>
              <el-button size="small" @click="applyAssertTemplate('status200')">状态码 200</el-button>
              <el-button size="small" @click="applyAssertTemplate('businessCode')">业务码为 0</el-button>
              <el-button size="small" @click="applyAssertTemplate('responseTime')">响应时间小于 1s</el-button>
            </div>
            <el-table :data="assertions" size="small" border>
              <el-table-column label="断言类型" width="200">
                <template #default="{ row }">
                  <el-select
                    v-model="row.type"
                    size="small"
                    @change="handleAssertTypeChange(row as AssertionRule)"
                  >
                    <el-option
                      v-for="item in assertTypeOptions"
                      :key="item.value"
                      :label="item.label"
                      :value="item.value"
                    />
                  </el-select>
                </template>
              </el-table-column>
              <el-table-column label="取值表达式" min-width="160">
                <template #default="{ row }">
                  <el-input
                    v-model="row.field"
                    size="small"
                    :disabled="!assertFieldEnabled(row.type)"
                    :placeholder="assertFieldEnabled(row.type) ? '如 $.data.token 或 Content-Type' : '该类型无需填写'"
                  />
                </template>
              </el-table-column>
              <el-table-column label="操作符" width="150">
                <template #default="{ row }">
                  <el-select
                    v-if="assertOpEnabled(row.type)"
                    v-model="row.op"
                    size="small"
                    filterable
                  >
                    <el-option
                      v-for="item in assertOpOptions"
                      :key="item.value"
                      :label="item.label"
                      :value="item.value"
                    />
                  </el-select>
                  <span v-else class="case-editor__hint">—</span>
                </template>
              </el-table-column>
              <el-table-column label="期望值" min-width="180">
                <template #default="{ row }">
                  <el-input
                    v-model="row.expected"
                    size="small"
                    :placeholder="assertExpectedPlaceholder(row.type)"
                  />
                </template>
              </el-table-column>
              <el-table-column label="备注" min-width="150">
                <template #default="{ row }">
                  <el-input v-model="row.message" size="small" placeholder="失败时的提示" />
                </template>
              </el-table-column>
              <el-table-column label="操作" width="70" align="center">
                <template #default="{ $index }">
                  <el-button text type="danger" :icon="Delete" @click="assertions.splice($index, 1)" />
                </template>
              </el-table-column>
              <template #empty>
                <span class="case-editor__empty">还没有断言，没有断言的用例只会校验请求是否成功</span>
              </template>
            </el-table>
            <el-button size="small" :icon="Plus" class="case-editor__add" @click="addAssertion">
              添加断言
            </el-button>
          </div>
        </el-form-item>
      </el-form>
    </div>

    <template #footer>
      <el-button @click="handleCancel">取消</el-button>
      <el-button type="primary" :loading="saving || submitting" @click="handleSave">保存</el-button>
    </template>
  </el-drawer>
</template>

<style scoped>
.case-editor {
  padding-bottom: 8px;
}

.case-editor__hint {
  margin-left: 10px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.case-editor__full {
  width: 100%;
}

.case-editor__method {
  width: 140px;
}

.case-editor__block {
  width: 100%;
}

.case-editor__add {
  margin-top: 8px;
}

.case-editor__templates {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.case-editor__empty {
  font-size: 12px;
  color: var(--el-text-color-placeholder);
}

:deep(.el-divider__text) {
  font-size: 13px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}
</style>
