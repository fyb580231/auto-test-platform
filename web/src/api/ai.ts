/**
 * AI 能力相关接口：状态查询、生成用例、失败归因、自然语言查报告。
 *
 * 未配置 DEEPSEEK_API_KEY 时后端会走 Mock 降级，响应中的 `mocked` 字段为 true，
 * 前端据此给出明确提示，避免把示例结果误认为真实模型输出。
 */
import { httpGet, httpPost } from '@/api/request'
import type {
  AiStatus,
  AnalyzeFailurePayload,
  FailureAnalysis,
  GenerateCasesPayload,
  GenerateCasesResponse,
  QueryReportPayload,
  QueryReportResponse,
} from '@/types'

/** AI 能力状态（前端据此提示当前是否为 Mock 模式） */
export function getAiStatus(): Promise<AiStatus> {
  return httpGet<AiStatus>('/ai/status')
}

/** 根据接口地址与业务描述生成接口用例 */
export function generateCases(payload: GenerateCasesPayload): Promise<GenerateCasesResponse> {
  return httpPost<GenerateCasesResponse>('/ai/generate-cases', payload)
}

/** 对失败任务做归因分析 */
export function analyzeFailure(payload: AnalyzeFailurePayload): Promise<FailureAnalysis> {
  return httpPost<FailureAnalysis>('/ai/analyze-failure', payload)
}

/** 自然语言查询测试报告 */
export function queryReport(payload: QueryReportPayload): Promise<QueryReportResponse> {
  return httpPost<QueryReportResponse>('/ai/query-report', payload)
}
