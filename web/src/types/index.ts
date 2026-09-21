/**
 * 与后端 `app/schemas` 严格对齐的 TypeScript 类型定义。
 *
 * 约定（来自后端 API 契约）：
 * 1. 成功响应**直接**是数据体：列表就是数组，分页就是 `PageResult<T>`，没有 `{code, data}` 外壳；
 * 2. 失败响应是 HTTP 4xx/5xx + `ApiErrorResponse`，由 `src/api/request.ts` 统一提示；
 * 3. 时间字段一律是 ISO 字符串。
 */

/* -------------------------------------------------------------------------- */
/* 基础类型                                                                    */
/* -------------------------------------------------------------------------- */

/** 用例类型 */
export type CaseType = 'api' | 'ui'

/** 任务状态 */
export type TaskStatus = 'pending' | 'running' | 'success' | 'failed' | 'error'

/** 单条用例的执行终态 */
export type CaseResultStatus = 'passed' | 'failed' | 'error' | 'skipped'

/** 用户角色 */
export type UserRole = 'admin' | 'member'

/** 断言类型 */
export type AssertType = 'status_code' | 'json_field' | 'response_time' | 'schema' | 'header'

/** 断言操作符 */
export type AssertOp =
  | 'eq'
  | 'ne'
  | 'contains'
  | 'not_contains'
  | 'gt'
  | 'lt'
  | 'ge'
  | 'le'
  | 'empty'
  | 'not_empty'
  | 'in'
  | 'regex'
  | 'length_eq'

/** UI 动作类型 */
export type UiAction =
  | 'open'
  | 'click'
  | 'input'
  | 'assert_visible'
  | 'assert_text'
  | 'assert_url'
  | 'assert_value'
  | 'wait'
  | 'select'
  | 'hover'
  | 'press'
  | 'screenshot'

/** 任务触发来源 */
export type TriggerType = 'manual' | 'schedule' | 'suite' | 'retry'

/**
 * 任意 JSON 值。
 *
 * 说明：这里刻意**不**写成递归类型别名（`... | JsonValue[] | { [key: string]: JsonValue }`）。
 * 递归 JSON 类型放进 `ref<...>` 之后，Vue 的 `UnwrapRefSimple` 会顺着递归一路展开，
 * 触发 TS2589（类型实例化过深）。改成宽松容器后，结构上仍然接受任意嵌套 JSON，
 * 只是不再对深层字段做精确推断——这些字段本就是后端透传的数据，前端只负责整体展示
 * （`prettyJson`）与整体回传，不需要逐层类型。
 */
export type JsonValue = string | number | boolean | null | JsonArray | JsonObject

/** JSON 数组 */
export type JsonArray = unknown[]

/** JSON 对象（请求头 / Query 参数 / 表单 / 响应体等） */
export interface JsonObject {
  [key: string]: unknown
}

/* -------------------------------------------------------------------------- */
/* 通用响应                                                                    */
/* -------------------------------------------------------------------------- */

/** 统一错误响应体 */
export interface ApiErrorResponse {
  success: false
  code: number
  message: string
  data: { errors?: string[] } | null
}

/** 统一简单操作响应 */
export interface MessageResponse<T = null> {
  success: boolean
  message: string
  data: T
}

/** 统一分页响应 */
export interface PageResult<T> {
  total: number
  page: number
  size: number
  items: T[]
}

/* -------------------------------------------------------------------------- */
/* 认证与用户                                                                  */
/* -------------------------------------------------------------------------- */

export interface UserInfo {
  id: number
  username: string
  email: string | null
  role: UserRole
  is_active: boolean
  created_at: string | null
}

export interface LoginPayload {
  username: string
  password: string
}

export interface RegisterPayload {
  username: string
  password: string
  email?: string
}

export interface LoginResponse {
  access_token: string
  token_type: string
  expires_in: number
  user: UserInfo
}

export interface ChangePasswordPayload {
  old_password: string
  new_password: string
}

/* -------------------------------------------------------------------------- */
/* 项目                                                                        */
/* -------------------------------------------------------------------------- */

export interface Project {
  id: number
  name: string
  description: string | null
  owner_id: number | null
  case_count: number
  suite_count: number
  environment_count: number
  created_at: string | null
  updated_at: string | null
}

export interface ProjectPayload {
  name: string
  description?: string | null
}

/* -------------------------------------------------------------------------- */
/* 环境                                                                        */
/* -------------------------------------------------------------------------- */

export interface Environment {
  id: number
  project_id: number
  name: string
  base_url: string
  headers: JsonObject
  variables: JsonObject
  verify: boolean
  timeout: number
  is_default: boolean
  description: string | null
  created_at: string | null
  updated_at: string | null
}

export interface EnvironmentPayload {
  name: string
  base_url: string
  headers: JsonObject
  variables: JsonObject
  verify: boolean
  timeout: number
  is_default: boolean
  description: string | null
}

/** 更新环境时所有字段可选 */
export type EnvironmentUpdatePayload = Partial<EnvironmentPayload>

/* -------------------------------------------------------------------------- */
/* 用例                                                                        */
/* -------------------------------------------------------------------------- */

/** 断言规则 */
export interface AssertionRule {
  type: AssertType
  expected?: JsonValue
  field?: string | null
  op: AssertOp
  message?: string | null
  name?: string | null
}

/** UI 步骤（open 动作把 URL 放在 value 字段里） */
export interface UiStep {
  action: UiAction
  selector?: string | null
  value?: string | null
  timeout?: number
  name?: string | null
}

/** 前置用例的变量提取规则 */
export interface ExtractRule {
  name: string
  path: string
}

export interface TestCase {
  id: number
  project_id: number
  name: string
  case_type: CaseType
  description: string | null
  tags: string[]
  method: string | null
  url: string | null
  headers: JsonObject
  params: JsonObject
  body: JsonValue
  form: JsonObject
  setup_case_id: number | null
  setup_case_name: string | null
  extract: ExtractRule[]
  steps: UiStep[]
  assertions: AssertionRule[]
  enabled: boolean
  created_at: string | null
  updated_at: string | null
}

/** 创建/更新用例的可写字段（后端会忽略 id / 派生字段） */
export interface CasePayload {
  name: string
  case_type: CaseType
  description: string | null
  tags: string[]
  method: string
  url: string
  headers: JsonObject
  params: JsonObject
  body: JsonValue
  form: JsonObject
  setup_case_id: number | null
  extract: ExtractRule[]
  steps: UiStep[]
  assertions: AssertionRule[]
  enabled: boolean
}

export type CaseUpdatePayload = Partial<CasePayload>

/** 用例列表查询条件 */
export interface CaseQuery {
  case_type?: CaseType | ''
  tag?: string
  keyword?: string
  enabled?: boolean
  page?: number
  size?: number
}

/** 批量执行用例请求 */
export interface BatchRunPayload {
  case_ids: number[]
  environment_id?: number | null
  retry_times?: number | null
  name?: string | null
}

/** 批量导入用例请求 */
export interface ImportCasesPayload {
  cases: CasePayload[]
  overwrite: boolean
}

/** 批量导入结果 */
export interface ImportResult {
  created: number
  updated: number
  skipped: number
}

/* -------------------------------------------------------------------------- */
/* 用例集                                                                      */
/* -------------------------------------------------------------------------- */

export interface TestSuite {
  id: number
  project_id: number
  name: string
  description: string | null
  case_ids: number[]
  case_count: number
  environment_id: number | null
  cron_expression: string | null
  retry_times: number
  enabled: boolean
  last_run_at: string | null
  created_at: string | null
  updated_at: string | null
}

export interface TestSuitePayload {
  name: string
  description?: string | null
  case_ids: number[]
  environment_id?: number | null
  cron_expression?: string | null
  retry_times: number
  enabled: boolean
}

export type TestSuiteUpdatePayload = Partial<TestSuitePayload>

export interface RunSuitePayload {
  environment_id?: number | null
  retry_times?: number | null
}

/** 调度器中的一条定时任务 */
export interface SchedulerJob {
  id: string
  name: string
  next_run_time: string | null
  trigger: string
}

export interface SchedulerJobsResponse {
  running: boolean
  jobs: SchedulerJob[]
}

/* -------------------------------------------------------------------------- */
/* 任务与报告                                                                  */
/* -------------------------------------------------------------------------- */

export interface Task {
  id: number
  task_no: string
  project_id: number | null
  project_name: string | null
  suite_id: number | null
  name: string
  trigger_type: string
  environment_name: string
  case_ids: number[]
  case_count: number
  status: TaskStatus
  total: number
  passed: number
  failed: number
  skipped: number
  pass_rate: number
  duration_ms: number
  started_at: string | null
  finished_at: string | null
  error_message: string | null
  has_ai_analysis: boolean
  created_at: string | null
}

/** 断言执行明细 */
export interface AssertionResultItem {
  label: string
  type: string
  expected: JsonValue
  actual: JsonValue
  passed: boolean
  message: string
}

/** UI 步骤执行明细 */
export interface UiStepResultItem {
  label: string
  action: string
  passed: boolean
  duration_ms: number
  message: string
  screenshots: string[]
}

/** 请求快照 */
export interface RequestSnapshot {
  method: string
  url: string
  params: JsonObject
  headers: JsonObject
  json: JsonValue
  data: JsonObject | null
}

/** 响应快照 */
export interface ResponseSnapshot {
  status_code: number
  elapsed_ms: number
  headers: JsonObject
  body: JsonValue
  text: string
}

/** 单条用例的执行结果 */
export interface CaseResult {
  case_id: string
  case_name: string
  case_type: CaseType
  status: CaseResultStatus
  duration_ms: number
  message: string
  traceback: string
  request: RequestSnapshot | null
  response: ResponseSnapshot | null
  assertions: AssertionResultItem[]
  screenshots: string[]
  steps: UiStepResultItem[]
  reruns: number
}

export interface TaskDetail extends Task {
  results: CaseResult[]
  log_path: string
  allure_results_dir: string
  /** 后端未生成 Allure 报告时为空字符串 */
  allure_report_url: string
  ai_analysis: string | null
  stdout_tail: string
}

export interface TaskLog {
  task_no: string
  content: string
  truncated: boolean
}

/** 任务列表查询条件 */
export interface TaskQuery {
  project_id?: number | null
  status?: TaskStatus | ''
  trigger_type?: string
  keyword?: string
  page?: number
  size?: number
}

/* -------------------------------------------------------------------------- */
/* Dashboard                                                                   */
/* -------------------------------------------------------------------------- */

export interface DashboardSummary {
  project_count: number
  case_count: number
  suite_count: number
  task_count_7d: number
  pass_rate_7d: number
  failed_task_count_7d: number
  avg_duration_ms: number
}

export interface TrendPoint {
  date: string
  total: number
  passed: number
  failed: number
  pass_rate: number
  task_count: number
}

export interface ProjectStat {
  project_id: number
  project_name: string
  task_count: number
  total: number
  passed: number
  failed: number
  pass_rate: number
}

export interface NameValueStat {
  name: string
  value: number
}

export interface DashboardStats {
  summary: DashboardSummary
  trend: TrendPoint[]
  project_stats: ProjectStat[]
  fail_distribution: NameValueStat[]
  status_distribution: NameValueStat[]
  recent_tasks: Task[]
  days: number
}

/* -------------------------------------------------------------------------- */
/* AI 能力                                                                     */
/* -------------------------------------------------------------------------- */

export interface AiStatus {
  enabled: boolean
  available: boolean
  /** 未配置 DEEPSEEK_API_KEY 时为 true，返回内置示例结果 */
  mocked: boolean
  model: string
  base_url: string
  message: string
}

export interface GenerateCasesPayload {
  url: string
  method: string
  description: string
  case_count: number
  tags: string[]
  extra_requirements?: string | null
}

export interface GenerateCasesResponse {
  cases: CasePayload[]
  model: string
  mocked: boolean
  usage: JsonObject
  raw: string
}

export interface AnalyzeFailurePayload {
  task_id: number
  case_result_index?: number | null
  include_request?: boolean
}

export interface FailureAnalysis {
  task_id: number
  case_name: string
  category: string
  summary: string
  reasons: string[]
  suggestions: string[]
  raw: string
  mocked: boolean
  usage: JsonObject
}

export interface QueryReportPayload {
  question: string
  days: number
}

export interface QueryReportResponse {
  question: string
  answer: string
  stats: JsonObject
  mocked: boolean
  usage: JsonObject
}
