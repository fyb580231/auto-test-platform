<!--
  EnvironmentConfig.vue —— 环境配置。

  职责：
  1. 左侧环境列表 + 右侧编辑表单（名称、base_url、公共 Headers、全局变量、校验证书、超时、默认环境、描述）；
  2. 新建 / 保存 / 删除，同一项目默认环境由后端保证唯一（前端给出即时提示）；
  3. 明确提示全局变量可在用例里用 {{变量名}} 引用。
-->
<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from 'element-plus'
import { Delete, Plus, Refresh } from '@element-plus/icons-vue'

import {
  createEnvironment,
  deleteEnvironment,
  listEnvironments,
  updateEnvironment,
} from '@/api/environment'
import { useProjectStore } from '@/stores/project'
import type { Environment, EnvironmentPayload, JsonObject } from '@/types'
import { formatDateTime } from '@/utils/format'

const projectStore = useProjectStore()

const loading = ref(false)
const saving = ref(false)
const environments = ref<Environment[]>([])
/** 当前选中的环境 ID；为 null 表示「新建」态 */
const selectedId = ref<number | null>(null)

const formRef = ref<FormInstance>()

const form = reactive({
  name: '',
  base_url: '',
  verify: true,
  timeout: 15,
  is_default: false,
  description: '',
})

/** JSON 字段以字符串编辑 */
const jsonTexts = reactive({
  headers: '{}',
  variables: '{}',
})

const jsonErrors = reactive({
  headers: '',
  variables: '',
})

type JsonKey = keyof typeof jsonTexts

const JSON_LABELS: Record<JsonKey, string> = {
  headers: '公共 Headers',
  variables: '全局变量',
}

/** 变量引用提示（写成常量，避免模板把 {{变量名}} 当成插值解析） */
const VARIABLE_HINT = '全局变量可在用例里用 {{变量名}} 引用'

const rules: FormRules<typeof form> = {
  name: [{ required: true, message: '请输入环境名称', trigger: 'blur' }],
}

/** 是否为新建态 */
const isCreating = computed(() => selectedId.value === null)
/** 当前项目名 */
const projectName = computed(() => projectStore.currentProject?.name ?? '未选择项目')

/* -------------------------------- 数据加载 ------------------------------- */
async function loadEnvironments(): Promise<void> {
  const projectId = projectStore.currentProjectId
  if (!projectId) {
    environments.value = []
    selectedId.value = null
    resetForm()
    return
  }
  loading.value = true
  try {
    environments.value = await listEnvironments(projectId)
    const current = environments.value.find((item) => item.id === selectedId.value)
    if (current) {
      fillForm(current)
    } else if (environments.value.length) {
      const first = environments.value[0]
      if (first) selectEnvironment(first)
    } else {
      selectedId.value = null
      resetForm()
    }
  } catch {
    // 错误提示已由 axios 拦截器统一处理
  } finally {
    loading.value = false
  }
}

/* -------------------------------- 表单操作 ------------------------------- */
/** 重置为新建态 */
function resetForm(): void {
  form.name = ''
  form.base_url = ''
  form.verify = true
  form.timeout = 15
  form.is_default = false
  form.description = ''
  jsonTexts.headers = '{}'
  jsonTexts.variables = '{}'
  jsonErrors.headers = ''
  jsonErrors.variables = ''
  void formRef.value?.clearValidate()
}

/** 用环境数据填充表单 */
function fillForm(environment: Environment): void {
  form.name = environment.name
  form.base_url = environment.base_url
  form.verify = environment.verify
  form.timeout = environment.timeout
  form.is_default = environment.is_default
  form.description = environment.description ?? ''
  jsonTexts.headers = JSON.stringify(environment.headers ?? {}, null, 2)
  jsonTexts.variables = JSON.stringify(environment.variables ?? {}, null, 2)
  jsonErrors.headers = ''
  jsonErrors.variables = ''
  void formRef.value?.clearValidate()
}

/** 选中某个环境 */
function selectEnvironment(environment: Environment): void {
  selectedId.value = environment.id
  fillForm(environment)
}

/** 点击「新建环境」 */
function handleCreate(): void {
  selectedId.value = null
  resetForm()
  // 第一个环境默认设为默认环境，减少一次手工勾选
  form.is_default = environments.value.length === 0
}

/** 顶部项目下拉切换 */
function handleProjectChange(value: unknown): void {
  if (value === undefined || value === null) return
  projectStore.setCurrentProject(Number(value))
}

/** 删除当前选中的环境 */
function handleDeleteCurrent(): void {
  const target = environments.value.find((item) => item.id === selectedId.value)
  if (target) void handleDelete(target)
}

/* ------------------------------ JSON 校验 ------------------------------ */
/** 校验某个 JSON 字段 */
function validateJson(key: JsonKey): boolean {
  const text = jsonTexts[key].trim()
  if (!text) {
    jsonErrors[key] = ''
    return true
  }
  try {
    const parsed: unknown = JSON.parse(text)
    if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
      jsonErrors[key] = `${JSON_LABELS[key]} 必须是 JSON 对象`
      return false
    }
    jsonErrors[key] = ''
    return true
  } catch (error) {
    const reason = error instanceof Error ? error.message : '无法解析'
    jsonErrors[key] = `${JSON_LABELS[key]} 不是合法 JSON：${reason}`
    return false
  }
}

/** 解析 JSON 字段为对象 */
function parseJson(key: JsonKey): JsonObject {
  const text = jsonTexts[key].trim()
  if (!text) return {}
  try {
    const parsed: unknown = JSON.parse(text)
    return typeof parsed === 'object' && parsed !== null && !Array.isArray(parsed)
      ? (parsed as JsonObject)
      : {}
  } catch {
    return {}
  }
}

/* --------------------------------- 保存 --------------------------------- */
async function handleSave(): Promise<void> {
  const projectId = projectStore.currentProjectId
  if (!projectId) {
    ElMessage.warning('请先选择当前项目')
    return
  }
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return
  if (!validateJson('headers') || !validateJson('variables')) {
    ElMessage.error('存在 JSON 格式错误，请修正后再保存')
    return
  }

  const payload: EnvironmentPayload = {
    name: form.name.trim(),
    base_url: form.base_url.trim(),
    headers: parseJson('headers'),
    variables: parseJson('variables'),
    verify: form.verify,
    timeout: form.timeout,
    is_default: form.is_default,
    description: form.description.trim() || null,
  }

  saving.value = true
  try {
    if (selectedId.value) {
      await updateEnvironment(selectedId.value, payload)
      ElMessage.success('环境已更新')
    } else {
      const created = await createEnvironment(projectId, payload)
      selectedId.value = created.id
      ElMessage.success('环境已创建')
    }
    await loadEnvironments()
  } catch {
    // 错误提示已由 axios 拦截器统一处理
  } finally {
    saving.value = false
  }
}

/* --------------------------------- 删除 --------------------------------- */
async function handleDelete(environment: Environment): Promise<void> {
  try {
    await ElMessageBox.confirm(
      `确认删除环境「${environment.name}」吗？引用该环境的用例集需要重新指定环境。`,
      '删除环境',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  try {
    const result = await deleteEnvironment(environment.id)
    ElMessage.success(result.message || '环境已删除')
    if (selectedId.value === environment.id) {
      selectedId.value = null
    }
    await loadEnvironments()
  } catch {
    // 错误提示已由 axios 拦截器统一处理
  }
}

/** 切换当前项目后重新加载环境列表 */
watch(
  () => projectStore.currentProjectId,
  () => {
    selectedId.value = null
    void loadEnvironments()
  },
)

onMounted(() => {
  if (!projectStore.projects.length) void projectStore.loadProjects().catch(() => undefined)
  void loadEnvironments()
})
</script>

<template>
  <div class="env-config">
    <el-card shadow="never" class="env-config__filter">
      <div class="env-config__filter-left">
        <span class="env-config__label">当前项目</span>
        <el-select
          :model-value="projectStore.currentProjectId ?? undefined"
          placeholder="请选择项目"
          class="env-config__project"
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
      <el-button :icon="Refresh" :disabled="!projectStore.currentProjectId" @click="loadEnvironments">
        刷新
      </el-button>
    </el-card>

    <el-empty v-if="!projectStore.currentProjectId" description="请先在「项目管理」选择当前项目" />

    <el-row v-else :gutter="16">
      <el-col :xs="24" :md="8" :lg="7">
        <el-card shadow="never" class="env-config__list-card">
          <template #header>
            <div class="env-config__list-header">
              <span>环境列表（{{ projectName }}）</span>
              <el-button type="primary" text :icon="Plus" @click="handleCreate">新建</el-button>
            </div>
          </template>

          <ul v-loading="loading" class="env-list">
            <li
              v-for="item in environments"
              :key="item.id"
              class="env-list__item"
              :class="{ 'env-list__item--active': item.id === selectedId }"
              @click="selectEnvironment(item)"
            >
              <div class="env-list__head">
                <span class="env-list__name">{{ item.name }}</span>
                <el-tag v-if="item.is_default" size="small" type="success" effect="plain">默认</el-tag>
              </div>
              <div class="env-list__url">{{ item.base_url || '未配置 base_url' }}</div>
              <div class="env-list__meta">超时 {{ item.timeout }}s · {{ formatDateTime(item.updated_at) }}</div>
            </li>
            <li v-if="!environments.length && !loading" class="env-list__empty">
              暂无环境，点击右上角「新建」
            </li>
          </ul>
        </el-card>
      </el-col>

      <el-col :xs="24" :md="16" :lg="17">
        <el-card shadow="never">
          <template #header>
            <div class="env-config__form-header">
              <span>{{ isCreating ? '新建环境' : `编辑环境：${form.name}` }}</span>
              <el-button
                v-if="!isCreating"
                text
                type="danger"
                :icon="Delete"
                @click="handleDeleteCurrent"
              >
                删除该环境
              </el-button>
            </div>
          </template>

          <el-alert
            type="info"
            :closable="false"
            show-icon
            :title="VARIABLE_HINT"
            description="例如变量 access_token 配置后，用例的 Headers 里写 Authorization: Bearer {{access_token}}；接口用例的 URL 写相对路径时会自动拼接 base_url。"
            class="env-config__alert"
          />

          <el-form ref="formRef" :model="form" :rules="rules" label-width="120px" @submit.prevent>
            <el-form-item label="环境名称" prop="name">
              <el-input v-model="form.name" placeholder="如 dev / staging / prod" maxlength="64" />
            </el-form-item>

            <el-form-item label="base_url">
              <el-input v-model="form.base_url" placeholder="如 http://127.0.0.1:8080（不带结尾斜杠）" />
            </el-form-item>

            <el-form-item label="公共 Headers" :error="jsonErrors.headers">
              <el-input
                v-model="jsonTexts.headers"
                type="textarea"
                :rows="4"
                resize="vertical"
                spellcheck="false"
                placeholder='{"Content-Type": "application/json"}'
                @input="validateJson('headers')"
              />
            </el-form-item>

            <el-form-item label="全局变量" :error="jsonErrors.variables">
              <el-input
                v-model="jsonTexts.variables"
                type="textarea"
                :rows="4"
                resize="vertical"
                spellcheck="false"
                placeholder='{"username": "admin", "password": "admin123"}'
                @input="validateJson('variables')"
              />
            </el-form-item>

            <el-form-item label="校验 HTTPS 证书">
              <el-switch v-model="form.verify" />
              <span class="env-config__hint">内网自签名证书的测试环境可关闭</span>
            </el-form-item>

            <el-form-item label="超时（秒）">
              <el-input-number v-model="form.timeout" :min="1" :max="600" controls-position="right" />
            </el-form-item>

            <el-form-item label="设为默认环境">
              <el-switch v-model="form.is_default" />
              <span class="env-config__hint">执行用例未指定环境时使用；同一项目仅保留一个默认环境</span>
            </el-form-item>

            <el-form-item label="描述">
              <el-input
                v-model="form.description"
                type="textarea"
                :rows="2"
                resize="none"
                maxlength="1000"
                placeholder="环境用途说明"
              />
            </el-form-item>

            <el-form-item>
              <el-button type="primary" :loading="saving" @click="handleSave">保存</el-button>
              <el-button v-if="isCreating" @click="handleCreate">重置</el-button>
            </el-form-item>
          </el-form>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<style scoped>
.env-config__filter {
  margin-bottom: 16px;
}

.env-config__filter :deep(.el-card__body) {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.env-config__filter-left {
  display: flex;
  align-items: center;
  gap: 10px;
}

.env-config__label {
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.env-config__project {
  width: 240px;
}

.env-config__list-card {
  margin-bottom: 16px;
}

.env-config__list-header,
.env-config__form-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-weight: 600;
}

.env-list {
  margin: 0;
  padding: 0;
  list-style: none;
  max-height: 560px;
  overflow-y: auto;
}

.env-list__item {
  padding: 10px 12px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 4px;
  margin-bottom: 8px;
  cursor: pointer;
  transition: border-color 0.2s, background-color 0.2s;
}

.env-list__item:hover {
  border-color: var(--el-color-primary-light-5);
}

.env-list__item--active {
  border-color: var(--el-color-primary);
  background-color: var(--el-color-primary-light-9);
}

.env-list__head {
  display: flex;
  align-items: center;
  gap: 8px;
}

.env-list__name {
  font-weight: 600;
}

.env-list__url {
  margin-top: 4px;
  font-size: 12px;
  color: var(--el-text-color-regular);
  word-break: break-all;
}

.env-list__meta {
  margin-top: 4px;
  font-size: 12px;
  color: var(--el-text-color-placeholder);
}

.env-list__empty {
  padding: 24px 0;
  text-align: center;
  font-size: 13px;
  color: var(--el-text-color-placeholder);
}

.env-config__alert {
  margin-bottom: 16px;
  white-space: pre-line;
}

.env-config__hint {
  margin-left: 10px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
</style>
