<!--
  AiAssistant.vue —— AI 助手对话面板（抽屉形式）。

  职责：
  1. 顶部展示 AI 能力状态，Mock 降级时用 `el-alert` 明确提示，避免把示例结果误认为真实模型输出；
  2. 对话式界面：用户 / AI 消息气泡，支持回车发送与快捷问题；
  3. 调用 `/ai/query-report` 查询测试报告，`answer` 按换行渲染（不引入 Markdown 库）；
  4. 回答下方用小字展示统计口径（统计窗口、任务数、用例数）。
-->
<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { ChatDotRound, Position, Promotion } from '@element-plus/icons-vue'

import { getAiStatus, queryReport } from '@/api/ai'
import type { AiStatus, JsonObject } from '@/types'

const props = defineProps<{
  /** 抽屉显隐 */
  modelValue: boolean
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: boolean): void
}>()

/** 统计窗口：与 Dashboard 图表口径保持一致 */
const STAT_DAYS = 7

/** 对话消息 */
interface ChatMessage {
  id: number
  role: 'user' | 'ai'
  content: string
  /** 统计口径（仅 AI 消息） */
  stats?: JsonObject
  /** 是否来自 Mock 降级 */
  mocked?: boolean
}

const visible = computed<boolean>({
  get: () => props.modelValue,
  set: (value: boolean) => emit('update:modelValue', value),
})

const status = ref<AiStatus | null>(null)
const question = ref('')
const sending = ref(false)
const messages = ref<ChatMessage[]>([])
const messageListRef = ref<HTMLDivElement>()

let messageSeed = 0

/** 快捷问题：覆盖「项目维度 / 整体通过率 / 失败最多的用例」三类高频问法 */
const quickQuestions = [
  '最近一周哪个项目失败最多？',
  '整体通过率是多少？',
  '失败最多的用例是哪些？',
]

/** AI 消息按行拆分，实现无 Markdown 库的轻量换行渲染 */
function renderLines(content: string): string[] {
  return content.split('\n').filter((line) => line.trim().length > 0)
}

/** 统计口径文案：展示 days / 任务数 / 用例数 */
function statsText(stats: JsonObject | undefined): string {
  if (!stats) return ''
  const summary = stats.summary
  const parts: string[] = [`统计窗口：最近 ${String(stats.days ?? STAT_DAYS)} 天`]
  if (summary && typeof summary === 'object' && !Array.isArray(summary)) {
    const summaryRecord = summary as Record<string, unknown>
    parts.push(`任务数：${String(summaryRecord.task_count ?? 0)}`)
    parts.push(`用例数：${String(summaryRecord.total_cases ?? 0)}`)
  }
  return parts.join(' · ')
}

/** 滚动到底部 */
async function scrollToBottom(): Promise<void> {
  await nextTick()
  const element = messageListRef.value
  if (element) {
    element.scrollTop = element.scrollHeight
  }
}

/** 追加一条消息 */
function pushMessage(message: Omit<ChatMessage, 'id'>): void {
  messageSeed += 1
  messages.value.push({ ...message, id: messageSeed })
  void scrollToBottom()
}

/** 发送问题 */
async function handleSend(preset?: string): Promise<void> {
  const content = (preset ?? question.value).trim()
  if (!content) {
    ElMessage.warning('请输入要查询的问题')
    return
  }
  if (sending.value) return

  pushMessage({ role: 'user', content })
  question.value = ''
  sending.value = true
  try {
    const result = await queryReport({ question: content, days: STAT_DAYS })
    pushMessage({
      role: 'ai',
      content: result.answer || '（模型未返回内容）',
      stats: result.stats,
      mocked: result.mocked,
    })
  } catch {
    // 错误提示已由 axios 拦截器统一处理
  } finally {
    sending.value = false
  }
}

onMounted(async () => {
  try {
    status.value = await getAiStatus()
  } catch {
    // 状态查询失败不影响对话功能
  }
})

// 首次打开抽屉时填入一条引导语，避免空白面板
watch(
  () => props.modelValue,
  (opened) => {
    if (opened && !messages.value.length) {
      pushMessage({
        role: 'ai',
        content:
          '你好，我可以基于执行记录回答测试报告相关的问题。\n可以点击下方快捷问题，或直接输入你的问题。',
      })
    }
  },
)
</script>

<template>
  <el-drawer v-model="visible" title="AI 助手" size="480px" :destroy-on-close="false">
    <div class="ai-assistant">
      <el-alert
        v-if="status"
        :type="status.mocked ? 'warning' : 'success'"
        :closable="false"
        show-icon
        class="ai-assistant__status"
      >
        <template #title>
          {{ status.mocked ? '当前为 Mock 模式' : '已接入真实模型' }}
        </template>
        <template #default>
          <span class="ai-assistant__status-text">
            {{
              status.mocked
                ? '未配置 DEEPSEEK_API_KEY，当前为 Mock 模式，返回内置示例结果'
                : `模型：${status.model}`
            }}
          </span>
        </template>
      </el-alert>

      <div ref="messageListRef" class="ai-assistant__messages">
        <div
          v-for="message in messages"
          :key="message.id"
          class="ai-message"
          :class="`ai-message--${message.role}`"
        >
          <div class="ai-message__bubble">
            <div v-for="(line, index) in renderLines(message.content)" :key="index" class="ai-message__line">
              {{ line }}
            </div>
          </div>
          <div v-if="message.role === 'ai' && message.stats" class="ai-message__meta">
            {{ statsText(message.stats) }}
            <el-tag v-if="message.mocked" size="small" type="warning" effect="plain">Mock 结果</el-tag>
          </div>
        </div>
        <div v-if="sending" class="ai-message ai-message--ai">
          <div class="ai-message__bubble ai-message__bubble--loading">
            <el-icon class="is-loading"><Position /></el-icon>
            正在分析执行记录…
          </div>
        </div>
      </div>

      <div class="ai-assistant__quick">
        <el-button
          v-for="item in quickQuestions"
          :key="item"
          size="small"
          plain
          :disabled="sending"
          @click="handleSend(item)"
        >
          {{ item }}
        </el-button>
      </div>

      <div class="ai-assistant__input">
        <el-input
          v-model="question"
          type="textarea"
          :rows="2"
          resize="none"
          placeholder="例如：最近一周哪个项目失败最多？"
          :disabled="sending"
          @keyup.enter.exact.prevent="handleSend()"
        />
        <el-button
          type="primary"
          :icon="Promotion"
          :loading="sending"
          class="ai-assistant__send"
          @click="handleSend()"
        >
          发送
        </el-button>
      </div>

      <p class="ai-assistant__tip">
        <el-icon><ChatDotRound /></el-icon>
        回答基于后端统计接口，与首页图表使用同一套统计口径。
      </p>
    </div>
  </el-drawer>
</template>

<style scoped>
.ai-assistant {
  display: flex;
  flex-direction: column;
  height: 100%;
}

.ai-assistant__status {
  margin-bottom: 12px;
}

.ai-assistant__status-text {
  font-size: 12px;
}

.ai-assistant__messages {
  flex: 1;
  min-height: 200px;
  overflow-y: auto;
  padding-right: 4px;
}

.ai-message {
  display: flex;
  flex-direction: column;
  margin-bottom: 14px;
}

.ai-message--user {
  align-items: flex-end;
}

.ai-message--ai {
  align-items: flex-start;
}

.ai-message__bubble {
  max-width: 92%;
  padding: 9px 12px;
  border-radius: 6px;
  font-size: 13px;
  line-height: 1.7;
  background-color: var(--el-fill-color-light);
  color: var(--el-text-color-primary);
  word-break: break-word;
}

.ai-message--user .ai-message__bubble {
  background-color: var(--el-color-primary-light-9);
  color: var(--el-color-primary-dark-2);
}

.ai-message__bubble--loading {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--el-text-color-secondary);
}

.ai-message__line {
  white-space: pre-wrap;
}

.ai-message__meta {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 6px;
  font-size: 12px;
  color: var(--el-text-color-placeholder);
}

.ai-assistant__quick {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin: 12px 0;
}

.ai-assistant__input {
  display: flex;
  align-items: flex-end;
  gap: 8px;
}

.ai-assistant__send {
  flex-shrink: 0;
}

.ai-assistant__tip {
  display: flex;
  align-items: center;
  gap: 4px;
  margin: 10px 0 0;
  font-size: 12px;
  color: var(--el-text-color-placeholder);
}
</style>
