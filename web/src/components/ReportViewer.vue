<!--
  ReportViewer.vue —— 任务执行报告查看器。

  职责（props: taskId）：
  1. 顶部汇总条：状态、用例总数、通过/失败/跳过、通过率、总耗时、执行环境；
  2. 用例结果列表（可按状态筛选），逐条展开请求 / 响应 / 断言明细 / UI 步骤 / 失败截图 / 错误堆栈；
  3. AI 失败归因分析（category / summary / reasons / suggestions 卡片化展示）；
  4. 控制台日志抽屉；
  5. Allure 原生报告入口（后端未生成时禁用并说明原因）。
-->
<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Document, MagicStick, Refresh, View } from '@element-plus/icons-vue'

import { analyzeFailure } from '@/api/ai'
import { getTask, getTaskLog } from '@/api/task'
import type { CaseResult, CaseResultStatus, FailureAnalysis, TaskDetail } from '@/types'
import {
  caseStatusTagType,
  caseStatusText,
  caseTypeText,
  formatDateTime,
  formatDuration,
  prettyJson,
  taskStatusTagType,
  taskStatusText,
  triggerTypeText,
} from '@/utils/format'

const props = defineProps<{
  /** 任务 ID */
  taskId: number
}>()

const loading = ref(false)
const detail = ref<TaskDetail | null>(null)

/** 结果状态筛选 */
const statusFilter = ref<CaseResultStatus | 'all'>('all')
/** 展开的用例结果（存下标） */
const activeResults = ref<string[]>([])
/** 展开错误堆栈的结果下标 */
const tracebackOpened = ref<Set<number>>(new Set())

/* ------------------------------- 日志抽屉 ------------------------------- */
const logVisible = ref(false)
const logLoading = ref(false)
const logContent = ref('')
const logTruncated = ref(false)

/* ------------------------------ AI 失败分析 ----------------------------- */
const analysis = ref<FailureAnalysis | null>(null)
const analyzing = ref(false)

/** 全部结果 */
const results = computed<CaseResult[]>(() => detail.value?.results ?? [])

/** 按状态筛选后的结果 */
const filteredResults = computed<CaseResult[]>(() => {
  if (statusFilter.value === 'all') return results.value
  return results.value.filter((item) => item.status === statusFilter.value)
})

/** 各状态数量，用于筛选按钮上的计数 */
const statusCounts = computed<Record<string, number>>(() => {
  const counts: Record<string, number> = { passed: 0, failed: 0, error: 0, skipped: 0 }
  results.value.forEach((item) => {
    counts[item.status] = (counts[item.status] ?? 0) + 1
  })
  return counts
})

/** 归因分类 -> Tag 颜色 */
function categoryTagType(category: string): 'success' | 'primary' | 'warning' | 'danger' | 'info' {
  if (category.includes('接口')) return 'danger'
  if (category.includes('脚本')) return 'warning'
  if (category.includes('环境')) return 'info'
  if (category.includes('用例')) return 'primary'
  return 'info'
}

/** 加载任务详情 */
async function loadDetail(): Promise<void> {
  if (!props.taskId) return
  loading.value = true
  try {
    detail.value = await getTask(props.taskId)
    analysis.value = null
    tracebackOpened.value = new Set()
    // 默认展开第一条失败用例，便于快速定位问题
    const firstFailedIndex = results.value.findIndex((item) => item.status !== 'passed')
    activeResults.value = firstFailedIndex >= 0 ? [String(firstFailedIndex)] : []
  } catch {
    // 错误提示已由 axios 拦截器统一处理
  } finally {
    loading.value = false
  }
}

/** 展开 / 收起错误堆栈 */
function toggleTraceback(index: number): void {
  const next = new Set(tracebackOpened.value)
  if (next.has(index)) {
    next.delete(index)
  } else {
    next.add(index)
  }
  tracebackOpened.value = next
}

/** 判断某条结果的堆栈是否展开 */
function isTracebackOpened(index: number): boolean {
  return tracebackOpened.value.has(index)
}

/** 查看控制台日志 */
async function openLog(): Promise<void> {
  if (!props.taskId) return
  logVisible.value = true
  logLoading.value = true
  try {
    const log = await getTaskLog(props.taskId)
    logContent.value = log.content || '暂无日志内容'
    logTruncated.value = log.truncated
  } catch {
    logContent.value = '日志读取失败'
  } finally {
    logLoading.value = false
  }
}

/** 触发 AI 失败归因分析（默认分析第一条失败用例） */
async function handleAnalyze(): Promise<void> {
  if (!props.taskId) return
  analyzing.value = true
  try {
    analysis.value = await analyzeFailure({ task_id: props.taskId, include_request: true })
    ElMessage.success('AI 归因分析完成')
  } catch {
    // 错误提示已由 axios 拦截器统一处理
  } finally {
    analyzing.value = false
  }
}

/** 打开 Allure 原生报告（后端已挂载在 /static/allure） */
function openAllureReport(): void {
  const url = detail.value?.allure_report_url
  if (!url) return
  window.open(url, '_blank', 'noopener')
}

watch(
  () => props.taskId,
  () => {
    void loadDetail()
  },
  { immediate: true },
)

// 供父组件在轮询时刷新报告（任务处于执行中时使用）
defineExpose({ reload: loadDetail })
</script>

<template>
  <div v-loading="loading" class="report-viewer">
    <template v-if="detail">
      <!-- 顶部汇总条 -->
      <div class="report-summary">
        <div class="report-summary__main">
          <el-tag :type="taskStatusTagType(detail.status)" size="large" effect="dark">
            {{ taskStatusText(detail.status) }}
          </el-tag>
          <div class="report-summary__title">
            <div class="report-summary__name">{{ detail.name }}</div>
            <div class="report-summary__no">
              {{ detail.task_no }} · {{ triggerTypeText(detail.trigger_type) }}
            </div>
          </div>
        </div>
        <div class="report-summary__metrics">
          <div class="metric">
            <span class="metric__label">用例总数</span>
            <span class="metric__value">{{ detail.total }}</span>
          </div>
          <div class="metric">
            <span class="metric__label">通过 / 失败 / 跳过</span>
            <span class="metric__value">
              <span class="text-success">{{ detail.passed }}</span> /
              <span class="text-danger">{{ detail.failed }}</span> /
              {{ detail.skipped }}
            </span>
          </div>
          <div class="metric">
            <span class="metric__label">通过率</span>
            <span class="metric__value">{{ detail.pass_rate.toFixed(1) }}%</span>
          </div>
          <div class="metric">
            <span class="metric__label">总耗时</span>
            <span class="metric__value">{{ formatDuration(detail.duration_ms) }}</span>
          </div>
          <div class="metric">
            <span class="metric__label">执行环境</span>
            <span class="metric__value">{{ detail.environment_name || '默认环境' }}</span>
          </div>
          <div class="metric">
            <span class="metric__label">开始时间</span>
            <span class="metric__value">{{ formatDateTime(detail.started_at) }}</span>
          </div>
        </div>
      </div>

      <el-alert
        v-if="detail.error_message"
        type="error"
        :closable="false"
        show-icon
        class="report-viewer__alert"
        title="执行器级错误"
        :description="detail.error_message"
      />

      <!-- 操作条 -->
      <div class="report-viewer__actions">
        <el-radio-group v-model="statusFilter" size="small">
          <el-radio-button value="all">全部（{{ results.length }}）</el-radio-button>
          <el-radio-button value="passed">通过（{{ statusCounts.passed }}）</el-radio-button>
          <el-radio-button value="failed">失败（{{ statusCounts.failed }}）</el-radio-button>
          <el-radio-button value="error">异常（{{ statusCounts.error }}）</el-radio-button>
          <el-radio-button value="skipped">跳过（{{ statusCounts.skipped }}）</el-radio-button>
        </el-radio-group>

        <div class="report-viewer__actions-right">
          <el-button size="small" :icon="Document" @click="openLog">查看控制台日志</el-button>
          <el-tooltip
            :disabled="Boolean(detail.allure_report_url)"
            content="当前环境未安装 allure CLI，平台内置报告已完整覆盖"
            placement="top"
          >
            <span>
              <el-button
                size="small"
                :icon="View"
                :disabled="!detail.allure_report_url"
                @click="openAllureReport"
              >
                打开 Allure 原生报告
              </el-button>
            </span>
          </el-tooltip>
          <el-button
            size="small"
            type="primary"
            :icon="MagicStick"
            :loading="analyzing"
            @click="handleAnalyze"
          >
            AI 失败分析
          </el-button>
          <el-button size="small" :icon="Refresh" @click="loadDetail">刷新</el-button>
        </div>
      </div>

      <!-- AI 分析结果 -->
      <el-card v-if="analysis" shadow="never" class="analysis-card">
        <template #header>
          <div class="analysis-card__header">
            <span>AI 失败归因分析</span>
            <span class="analysis-card__case">{{ analysis.case_name || '未指定用例' }}</span>
          </div>
        </template>
        <div class="analysis-card__category">
          <el-tag :type="categoryTagType(analysis.category)" effect="light">
            {{ analysis.category }}
          </el-tag>
          <el-tag v-if="analysis.mocked" type="warning" effect="plain" size="small">
            Mock 模式结果
          </el-tag>
        </div>
        <p class="analysis-card__summary">{{ analysis.summary || '（模型未返回结论）' }}</p>
        <div v-if="analysis.reasons.length" class="analysis-card__block">
          <div class="analysis-card__block-title">判断依据</div>
          <ul class="analysis-card__list">
            <li v-for="(reason, index) in analysis.reasons" :key="index">{{ reason }}</li>
          </ul>
        </div>
        <div v-if="analysis.suggestions.length" class="analysis-card__block">
          <div class="analysis-card__block-title">修复建议</div>
          <ol class="analysis-card__list">
            <li v-for="(item, index) in analysis.suggestions" :key="index">{{ item }}</li>
          </ol>
        </div>
      </el-card>

      <!-- 用例结果列表 -->
      <el-empty v-if="!filteredResults.length" description="没有符合筛选条件的执行结果" :image-size="90" />

      <el-collapse v-else v-model="activeResults" class="result-collapse">
        <el-collapse-item
          v-for="(item, index) in filteredResults"
          :key="`${item.case_id}-${index}`"
          :name="String(index)"
        >
          <template #title>
            <div class="result-title">
              <el-tag :type="caseStatusTagType(item.status)" size="small" effect="light">
                {{ caseStatusText(item.status) }}
              </el-tag>
              <span class="result-title__name">{{ item.case_name }}</span>
              <el-tag size="small" type="info" effect="plain">
                {{ caseTypeText(item.case_type) }}
              </el-tag>
              <span class="result-title__meta">{{ formatDuration(item.duration_ms) }}</span>
              <span v-if="item.reruns" class="result-title__meta">重跑 {{ item.reruns }} 次</span>
            </div>
          </template>

          <div class="result-body">
            <el-alert
              v-if="item.message"
              type="error"
              :closable="false"
              show-icon
              :title="item.message"
              class="result-body__message"
            />

            <!-- 请求 / 响应 -->
            <div v-if="item.case_type === 'api'" class="result-grid">
              <div class="result-block">
                <div class="result-block__title">请求详情</div>
                <div class="kv-row">
                  <span class="kv-row__label">方法</span>
                  <span class="kv-row__value">{{ item.request?.method ?? '-' }}</span>
                </div>
                <div class="kv-row">
                  <span class="kv-row__label">URL</span>
                  <span class="kv-row__value kv-row__value--mono">{{ item.request?.url ?? '-' }}</span>
                </div>
                <div class="result-block__subtitle">Headers</div>
                <pre class="code-block">{{ prettyJson(item.request?.headers, '无') }}</pre>
                <div class="result-block__subtitle">Query 参数</div>
                <pre class="code-block">{{ prettyJson(item.request?.params, '无') }}</pre>
                <div class="result-block__subtitle">Body</div>
                <pre class="code-block">{{ prettyJson(item.request?.json, '无') }}</pre>
              </div>

              <div class="result-block">
                <div class="result-block__title">响应详情</div>
                <div class="kv-row">
                  <span class="kv-row__label">状态码</span>
                  <span
                    class="kv-row__value"
                    :class="(item.response?.status_code ?? 0) >= 400 ? 'text-danger' : 'text-success'"
                  >
                    {{ item.response?.status_code ?? '-' }}
                  </span>
                </div>
                <div class="kv-row">
                  <span class="kv-row__label">耗时</span>
                  <span class="kv-row__value">{{ formatDuration(item.response?.elapsed_ms ?? 0) }}</span>
                </div>
                <div class="result-block__subtitle">Headers</div>
                <pre class="code-block">{{ prettyJson(item.response?.headers, '无') }}</pre>
                <div class="result-block__subtitle">Body</div>
                <pre class="code-block">{{ prettyJson(item.response?.body, '无') }}</pre>
              </div>
            </div>

            <!-- 断言明细 -->
            <div v-if="item.assertions.length" class="result-section">
              <div class="result-block__title">断言明细</div>
              <el-table
                :data="item.assertions"
                size="small"
                border
                :row-class-name="({ row }) => (row.passed ? '' : 'row-failed')"
              >
                <el-table-column prop="label" label="断言描述" min-width="200" show-overflow-tooltip />
                <el-table-column prop="type" label="类型" width="120" />
                <el-table-column label="期望值" min-width="140" show-overflow-tooltip>
                  <template #default="{ row }">{{ prettyJson(row.expected, '-') }}</template>
                </el-table-column>
                <el-table-column label="实际值" min-width="140" show-overflow-tooltip>
                  <template #default="{ row }">{{ prettyJson(row.actual, '-') }}</template>
                </el-table-column>
                <el-table-column label="结果" width="80">
                  <template #default="{ row }">
                    <el-tag :type="row.passed ? 'success' : 'danger'" size="small" effect="light">
                      {{ row.passed ? '通过' : '失败' }}
                    </el-tag>
                  </template>
                </el-table-column>
                <el-table-column prop="message" label="说明" min-width="160" show-overflow-tooltip />
              </el-table>
            </div>

            <!-- UI 步骤 -->
            <div v-if="item.steps.length" class="result-section">
              <div class="result-block__title">UI 步骤执行明细</div>
              <el-table
                :data="item.steps"
                size="small"
                border
                :row-class-name="({ row }) => (row.passed ? '' : 'row-failed')"
              >
                <el-table-column prop="label" label="步骤" min-width="220" show-overflow-tooltip />
                <el-table-column prop="action" label="动作" width="140" />
                <el-table-column label="结果" width="80">
                  <template #default="{ row }">
                    <el-tag :type="row.passed ? 'success' : 'danger'" size="small" effect="light">
                      {{ row.passed ? '通过' : '失败' }}
                    </el-tag>
                  </template>
                </el-table-column>
                <el-table-column label="耗时" width="100">
                  <template #default="{ row }">{{ formatDuration(row.duration_ms) }}</template>
                </el-table-column>
                <el-table-column prop="message" label="失败原因" min-width="180" show-overflow-tooltip />
              </el-table>
            </div>

            <!-- 失败截图 -->
            <div v-if="item.screenshots.length" class="result-section">
              <div class="result-block__title">失败截图</div>
              <div class="screenshot-list">
                <el-image
                  v-for="(url, shotIndex) in item.screenshots"
                  :key="url"
                  :src="url"
                  :preview-src-list="item.screenshots"
                  :initial-index="shotIndex"
                  fit="contain"
                  class="screenshot"
                  preview-teleported
                />
              </div>
            </div>

            <!-- 错误堆栈 -->
            <div v-if="item.traceback" class="result-section">
              <el-button text type="danger" @click="toggleTraceback(index)">
                {{ isTracebackOpened(index) ? '收起错误堆栈' : '查看错误堆栈' }}
              </el-button>
              <pre v-if="isTracebackOpened(index)" class="code-block">{{ item.traceback }}</pre>
            </div>
          </div>
        </el-collapse-item>
      </el-collapse>
    </template>

    <el-empty v-else-if="!loading" description="暂无报告数据" />

    <!-- 控制台日志 -->
    <el-drawer v-model="logVisible" title="控制台日志" size="560px">
      <div v-loading="logLoading" class="log-drawer">
        <el-alert
          v-if="logTruncated"
          type="warning"
          :closable="false"
          show-icon
          title="日志内容过长，仅展示末尾部分"
          class="log-drawer__alert"
        />
        <pre class="code-block log-drawer__content">{{ logContent }}</pre>
      </div>
    </el-drawer>
  </div>
</template>

<style scoped>
.report-viewer {
  min-height: 200px;
}

.report-summary {
  padding: 14px 16px;
  background-color: var(--el-fill-color-lighter);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
}

.report-summary__main {
  display: flex;
  align-items: center;
  gap: 12px;
}

.report-summary__name {
  font-size: 15px;
  font-weight: 600;
}

.report-summary__no {
  margin-top: 2px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.report-summary__metrics {
  display: flex;
  flex-wrap: wrap;
  gap: 32px;
  margin-top: 14px;
  padding-top: 12px;
  border-top: 1px dashed var(--el-border-color);
}

.metric {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.metric__label {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.metric__value {
  font-size: 14px;
  font-weight: 600;
}

.report-viewer__alert {
  margin-top: 12px;
}

.report-viewer__actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px;
  margin: 16px 0;
}

.report-viewer__actions-right {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.analysis-card {
  margin-bottom: 16px;
  border-color: var(--el-border-color-lighter);
}

.analysis-card__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-weight: 600;
}

.analysis-card__case {
  font-size: 12px;
  font-weight: 400;
  color: var(--el-text-color-secondary);
}

.analysis-card__category {
  display: flex;
  align-items: center;
  gap: 8px;
}

.analysis-card__summary {
  margin: 12px 0;
  font-size: 14px;
  line-height: 1.7;
}

.analysis-card__block {
  margin-top: 12px;
}

.analysis-card__block-title {
  margin-bottom: 6px;
  font-size: 13px;
  font-weight: 600;
  color: var(--el-text-color-regular);
}

.analysis-card__list {
  margin: 0;
  padding-left: 20px;
  font-size: 13px;
  line-height: 1.8;
  color: var(--el-text-color-regular);
}

.result-collapse {
  border-top: none;
}

.result-title {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  overflow: hidden;
}

.result-title__name {
  font-weight: 600;
}

.result-title__meta {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.result-body {
  padding: 4px 0 8px;
}

.result-body__message {
  margin-bottom: 12px;
}

.result-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
  gap: 16px;
}

.result-block {
  min-width: 0;
}

.result-block__title {
  margin-bottom: 8px;
  font-size: 13px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}

.result-block__subtitle {
  margin: 10px 0 4px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.result-section {
  margin-top: 16px;
}

.kv-row {
  display: flex;
  gap: 8px;
  font-size: 13px;
  line-height: 1.8;
}

.kv-row__label {
  width: 56px;
  flex-shrink: 0;
  color: var(--el-text-color-secondary);
}

.kv-row__value--mono {
  font-family: Consolas, Monaco, 'Courier New', monospace;
  word-break: break-all;
}

.text-success {
  color: var(--el-color-success);
}

.text-danger {
  color: var(--el-color-danger);
}

.screenshot-list {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
}

.screenshot {
  width: 220px;
  height: 140px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 4px;
  background-color: var(--el-fill-color-lighter);
}

.log-drawer__alert {
  margin-bottom: 12px;
}

.log-drawer__content {
  max-height: calc(100vh - 140px);
}

:deep(.row-failed) {
  --el-table-tr-bg-color: var(--el-color-danger-light-9);
}
</style>
