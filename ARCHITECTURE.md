# ARCHITECTURE.md

> auto-test-platform 的分层设计、关键契约与实现取舍。
> 面向需要改动这份代码的人——读完应该能回答「我该把新功能加在哪一层」。

---

## 1. 设计目标与约束

这份架构由四条约束推导而来，**每条约束都对应一处实际的代码结构**：

| 约束 | 推导出的结构 |
| --- | --- |
| 用例应该是数据，不是代码 | 用例存 YAML / 数据库，`pytest.mark.parametrize` 动态参数化，新增用例零代码改动 |
| 引擎必须能脱离 Web 独立运行 | `engine/` 不 import `app/` 的任何模块，`run_engine.py` 提供第二入口 |
| 平台不能因为用户跑测试而失稳 | 任务级并发上限 + 每任务独立 pytest 子进程 + 超时强杀 |
| AI 不能成为可用性的单点 | 三重降级触发 + 调用异常二次降级 + 基于真实数据的规则兜底 |

第 1 条和第 2 条共同决定了本项目最核心的一个设计：**服务层与引擎层之间不通过对象传值，而是通过跨进程的文件契约通信。**

---

## 2. 分层与依赖规则

### 2.1 三层职责

```
web/      可视化层      ——  只认 HTTP 契约，不关心后端实现
  │  HTTP
app/      服务层        ——  认证、持久化、编排、聚合、AI；不实现测试执行细节
  │  进程内调用 + 文件契约
engine/   引擎层        ——  纯执行能力；不知道数据库、权限、HTTP 服务的存在
  │  子进程
testcases/ 运行期入口   ——  pytest 的挂载点，把载荷参数化成测试项
```

### 2.2 依赖规则（硬约束）

```
web  →  app  →  engine          ✅ 允许
engine  →  app                  ❌ 禁止
engine  →  web                  ❌ 禁止
app  →  web                     ❌ 禁止
```

这条规则在代码里有明确的落点，`testcases/conftest.py` 的文件头注释就是这条规则的看门人：

> 本文件必须保持「零业务依赖」——它不能 import `app/` 下的任何模块，否则引擎层就无法脱离 Web 独立运行了。

`app` 与 `engine` 之间只有两处 import，方向都是单向的：

- `app/services/test_runner.py` → `from engine.runner import PytestRunner, RunSummary`
- `app/services/seed.py` → `from engine.data_loader import DataLoader, DataLoadError`

**评审检查点**：任何让 `engine/` 或 `testcases/` 出现 `from app...` / `import app...` 的改动，都是对架构的破坏，应当直接打回。

### 2.3 为什么这条规则值得维护

因为它是「引擎能被任意 CI 复用」这个卖点的**唯一实现方式**。一旦 `engine` 里出现对 `settings` 或 ORM 的依赖，它就必须在能 import 到整个后端工程的环境里才能运行，`python run_engine.py --file xxx.yaml` 这个入口会立刻失效。

---

## 3. 运行时拓扑

### 3.1 开发形态

```
Vite Dev Server (:5173)                 FastAPI (uvicorn, :8000)
  ├─ /api    ──── proxy ───────────────────→  /api/*
  └─ /static ──── proxy ───────────────────→  /static/*   （截图、Allure HTML）
```

代理配置见 `web/vite.config.ts`，因此开发期**不存在跨域问题**；`CORS_ORIGINS` 主要为生产部署的同域/跨域场景保留。

### 3.2 生产形态（预期，容器编排文件尚未提供）

```
Browser ──→ nginx (:80, web/nginx.conf)
              ├─ /            → SPA，try_files 回退 index.html
              ├─ /api/        → http://backend:8000
              └─ /static/     → http://backend:8000
```

nginx 与后端同源反代，浏览器侧同样无跨域。注意 `web/nginx.conf` 里的上游写的是容器名 `backend`，说明预期是 docker-compose 部署；目前仓库**没有 `Dockerfile` / `docker-compose.yml`**，这是已知缺口（见 `README.md` 的「已知限制」）。

### 3.3 进程模型

单个 uvicorn 进程内：

```
主进程
 ├─ FastAPI 应用（含 lifespan 初始化的建表 / 演示数据 / APScheduler）
 ├─ ThreadPoolExecutor(max_workers=MAX_CONCURRENT_TASKS)   ← 任务调度
 └─ 每个任务：subprocess.run(python -m pytest ...)          ← 用例执行
```

**关键点：真正的用例执行发生在子进程里，主进程只做编排与结果落库。** 因此被测逻辑的崩溃、内存泄漏、GIL 占用都不会直接影响 Web 服务的响应能力。

---

## 4. 数据模型

6 张表，全部通过 `app/models/__init__.py` 统一导出（保证 `create_all` 能看到全部元数据）。

```
users ──┐
        │ owner_id (SET NULL)
        ▼
     projects ──┬──(CASCADE)──→ environments      (project_id + name 唯一)
                │
                ├──(CASCADE)──→ test_cases         (含 setup_case_id 自引用，SET NULL)
                │
                └──(CASCADE)──→ test_suites
                                     │ suite_id (SET NULL)
                                     ▼
                                  tasks      ← 也直接引用 project_id
```

### 4.1 表与关键字段

| 表 | 关键字段 | 说明 |
| --- | --- | --- |
| `users` | `username`(唯一)、`hashed_password`、`email`、`role`、`is_active` | `role` ∈ admin / member |
| `projects` | `name`(唯一)、`description`、`owner_id` | 删除项目级联删用例、环境、用例集 |
| `environments` | `project_id`、`name`、`base_url`、`headers`(JSON)、`variables`(JSON)、`verify`、`timeout`、`is_default` | 一个项目内 `(project_id, name)` 唯一 |
| `test_cases` | `case_type`、`tags`(JSON)、`method`、`url`、`headers`/`params`/`body`/`form`(JSON)、`extract`(JSON)、`steps`(JSON, UI)、`assertions`(JSON)、`setup_case_id` | 接口与 UI 用例共用一张表，靠 `case_type` 区分 |
| `test_suites` | `project_id`、`case_ids`(JSON)、`environment_id`、`cron_expression`、`retry_times`、`enabled`、`last_run_at` | 用例集 = 用例 ID 列表 + 环境 + 调度表达式 |
| `tasks` | `project_id`、`suite_id`、`case_ids`(JSON)、`status`、`trigger_type`、`total`/`passed`/`failed`/`skipped`、`pass_rate`、`duration_ms`、`result_detail`(JSON) | 一次执行的完整记录 |

### 4.2 状态机

**任务状态 `TaskStatus`**：

```
pending ──→ running ──┬──→ success
   ▲                  ├──→ failed     （有失败用例，属正常执行结果）
   │                  └──→ error      （执行器异常 / 超时 / 无法判定）
   └── retry 会新建一条 pending 任务（不修改原记录）
```

终态由 `Task.is_finished` 定义。落点：创建时 `pending` → 执行开始置 `running` → `_apply_summary()` 时按汇总结果写终态 → 执行器抛异常时 `_mark_task_error()` 写 `error`。

**用例结果状态**：`passed` / `failed` / `error` / `skipped`（`engine/runner.py` 定义）。

**触发类型 `TriggerType`**：`manual`（默认）与 `schedule`（调度器写入）。枚举里的 `ci` **当前无赋值入口**——引擎侧没有回写通道，这是已知缺口。

### 4.3 两个刻意的设计选择

**① Task 存的是一份「执行快照」而不是一组外键。**
`tasks` 里冗余了 `case_ids`、`environment_name`，`environment_id` 甚至是裸 Integer（无外键约束）。原因是：**历史执行记录不应该因为用例被改名、环境被删除而失真**。一个任务跑到一半，用户把用例删了，历史报告仍然要能显示当时跑的是什么。这是典型的"用一点冗余换数据不可变性"的取舍。

**② 大量使用 JSON 列而不是关联表。**
`tags`、`assertions`、`steps`、`case_ids` 都是 JSON 列。理由是用例的断言与步骤是**整体读写的值对象**，不存在"按某条断言查询"的需求；拆成关联表会让每次读写都变成 N+1，而收益为零。代价是无法在数据库层对这些内容做索引与约束——被接受。

---

## 5. 执行编排

### 5.1 触发入口

| 入口 | 接口 | 说明 |
| --- | --- | --- |
| 单条执行 | `POST /api/testcases/{case_id}/run` | 跑一条用例 |
| 批量执行 | `POST /api/testcases/batch-run` | 勾选多条用例 |
| 用例集执行 | `POST /api/testsuites/{suite_id}/run` | 按用例集执行，可覆盖环境与重跑次数 |
| 整任务重跑 | `POST /api/tasks/{task_id}/retry` | 复制原任务配置，新建一条 pending 任务 |
| 定时触发 | APScheduler → `trigger_suite()` | 与用例集执行同链路，`trigger_type=schedule` |

### 5.2 完整时序

```
①  HTTP 请求（已通过 JWT 鉴权）
        │
②  路由层：查用例 / 校验入参 → TestRunnerService(db).create_task(...)
        │   · 生成 task_no = uuid4().hex
        │   · 解析环境：显式指定 > 项目默认 > 项目第一个 > None
        │   · 写库，status = pending
        │
③  serialize_task() 生成响应体，同时 service.submit(task_id)
        │   ← 不等待执行完成，立即返回任务 ID（异步执行）
        │
④  submit() → _EXECUTOR.submit(run_task, task_id)
        │
⑤  run_task()（工作线程）
        │   · _RUNNING_TASKS 去重 —— 防用户连点造成重复执行
        │   · _SEMAPHORE.acquire() —— 卡住任务级并发上限
        │   · TaskExecutor(task_id).run()
        │
⑥  TaskExecutor.run()
        │   · 新开独立 SessionLocal（工作线程不能复用请求会话）
        │   · status = running, started_at = now
        │   · _build_payloads()：ORM → 引擎载荷，跳过停用用例
        │   · _build_env_config()：环境 → base_url / headers / variables
        │   └─ runner.run(task_id, task_no, env, cases, retry_times)
        │              │
        │              ├─ _prepare_dirs()：建 reports/{generated,logs,screenshots/<id>,allure-results/<id>}
        │              ├─ 写载荷文件 reports/generated/cases_<task_no>.json
        │              ├─ 构建命令并启动子进程：
        │              │     sys.executable -m pytest testcases/test_dynamic_cases.py
        │              │       -p no:cacheprovider -v
        │              │       --alluredir=<...> --clean-alluredir
        │              │       [--reruns=N --reruns-delay=1]
        │              │     env: ATP_CASE_FILE / ATP_RESULT_FILE / ATP_TASK_ID /
        │              │          ATP_SCREENSHOT_DIR / PYTHONPATH /
        │              │          PYTHONIOENCODING=utf-8 / PYTHONDONTWRITEBYTECODE=1
        │              │     cwd = 项目根目录
        │              │     timeout = PYTEST_TIMEOUT_SECONDS（超时则强杀并记 error）
        │              │
        │              │   ┌── 子进程内 ────────────────────────────────┐
        │              │   │ conftest 加载载荷 → env_config fixture      │
        │              │   │ parametrize 展开成 N 条测试项               │
        │              │   │ 每条：execute_case() → _execute_api_case()  │
        │              │   │       或 _execute_ui_case()                │
        │              │   │ 明细写入进程内 CaseTelemetry                │
        │              │   │ makereport 钩子记录状态/耗时/重跑次数        │
        │              │   │ sessionfinish 写出 ATP_RESULT_FILE         │
        │              │   └────────────────────────────────────────────┘
        │              │
        │              ├─ _collect()：读回结果 JSON，逐条构造 CaseResult
        │              ├─ 结果文件缺失 → 用载荷兜底并标 error
        │              └─ 判定 overall status（见 5.4）
        │
        ├─ _apply_summary()：写 total / passed / failed / skipped / pass_rate /
        │                    duration_ms / result_detail / finished_at
        └─ _generate_allure_report()：调 allure CLI 生成 HTML（失败只记日志，不影响任务状态）
```

### 5.3 为什么用子进程而不是 `pytest.main()`

| 维度 | `pytest.main()`（同进程） | `subprocess`（子进程）✅ |
| --- | --- | --- |
| 崩溃隔离 | 用例里的段错误 / `os._exit` / C 扩展崩溃会带走整个 Web 服务 | 只死子进程，服务无感 |
| 超时控制 | 无法从外部安全打断线程，超时形同虚设 | `subprocess` 可终止进程，超时真正生效 |
| GIL | 与被测逻辑争抢 | 完全隔离 |
| 资源清理 | 用例残留的全局状态污染服务进程 | 进程退出即回收 |

代价是每次任务多一次解释器启动 + pytest 插件加载的开销，以及父子进程只能通过文件与环境变量通信。对"跑测试不能拖垮服务"这个目标来说，这是划算的。

### 5.4 结果判定规则

```
超时 或 结果文件缺失              → error
失败数为 0 且 退出码 ∈ {0, 5}     → success   （5 = 未收集到用例，也算成功）
失败数为 0 且 存在通过的用例       → success
其余                              → failed
```

显式处理退出码 5 很重要：用例集为空时 pytest 返回 5，这不该被当成失败。

### 5.5 并发模型

```
任务级并发：ThreadPoolExecutor(max_workers=MAX_CONCURRENT_TASKS)  ← 默认 4
            + BoundedSemaphore(MAX_CONCURRENT_TASKS)              ← 双保险
            + _RUNNING_TASKS 集合                                  ← 同任务去重
任务内：    串行（一条一条跑）
```

用信号量而非仅靠线程池，是因为线程池无法阻止**同一个任务被重复提交**（用户连点"执行"），所以额外用集合做了去重。

**任务内为什么串行**：`CaseTelemetry` 是在被测进程内记录请求、响应、断言明细的进程内单例。若上 pytest-xdist，worker 是独立进程，这些明细需要跨进程回传与合并，会让这条链路复杂度显著上升。因此并行度以配置项 `PYTEST_MAX_WORKERS` **显式预留**，而不是实现一个半成品。

---

## 6. 引擎层与服务层的契约

这是整个架构里最需要小心维护的部分。

### 6.1 契约的四个组成

| 组成 | 位置 | 作用 |
| --- | --- | --- |
| 载荷文件 | `ATP_CASE_FILE` → `reports/generated/cases_<task_no>.json` | 服务层 → 引擎层：本次要跑什么 |
| 结果文件 | `ATP_RESULT_FILE` → 同目录 `results_<task_no>.json` | 引擎层 → 服务层：跑出了什么 |
| 进程内遥测 | `engine.runner.CaseTelemetry` | 引擎层内部：请求/响应/断言/截图明细的收集点 |
| 环境变量 | `ATP_TASK_ID` / `ATP_SCREENSHOT_DIR` | 上下文透传（截图目录、任务标识） |

### 6.2 载荷结构

```json
{
  "task_id": "…",
  "env":     { "base_url": "…", "headers": {…}, "variables": {…}, "verify": true, "timeout": 30 },
  "cases":   [ { "id": "api_001", "case_type": "api", "request": {…}, "assertions": [ … ] } ]
}
```

### 6.3 结果结构

```json
{
  "task_id": "…",
  "results": [
    {
      "case_id": "api_001",
      "case_name": "…",
      "case_type": "api",
      "status": "passed | failed | error | skipped",
      "duration_ms": 123.45,
      "message": "失败摘要",
      "traceback": "完整堆栈",
      "request":  { "method": "GET", "url": "…", "headers": {…} },
      "response": { "status_code": 200, "body": "…" },
      "assertions": [ { "name": "…", "passed": true, "expected": …, "actual": … } ],
      "screenshots": ["…"], "steps": [ … ],
      "reruns": 0
    }
  ]
}
```

### 6.4 结果收集插件的工作方式

`testcases/conftest.py` 是这份契约在子进程内的实现方：

- `pytest_configure` → 建立 `ResultCollector` 单例；
- `pytest_runtest_makereport`（hookwrapper）→ 记录每条用例的终态；
- `pytest_sessionfinish` → 把结果写入 `ATP_RESULT_FILE`。

**重跑次数统计的一个细节**：`pytest-rerunfailures` 会把中间失败的 outcome 标成 `rerun`，但不同版本的行为不一致（有的在 `makereport` 阶段就改了 outcome，有的只在 `logreport` 阶段改）。因此代码**不依赖插件的 outcome 标记**，而是数 call 阶段报告出现的次数来推算重跑次数（`reruns = attempts - 1`），做到与插件版本无关。

**另一个细节**：失败摘要 `_short_message()` 会从 `longrepr` 里倒序查找第一行真正可读的内容并跳过 `E ` / `>` / `|` 这些 pytest 输出修饰符，让前端的失败提示不出现满屏代码。

### 6.5 为什么不用消息队列 / RPC

因为契约要同时服务两种调用方：平台（服务层调度）与 CLI（`run_engine.py` 直接调用）。文件 + 环境变量是唯一两种模式都能满足的最小方案，而且**天然带审计痕迹**——每次执行留下载荷与结果两个 JSON，排查问题时可以直接看当时到底下发了什么。用消息队列会引入外部依赖，破坏"引擎可以单文件跑起来"的特性。

---

## 7. 用例数据模型

### 7.1 双来源归一化

用例有两个来源，最终必须收敛成同一种内部结构：

```
平台数据库（TestCase ORM）
        │  TestCase.to_engine_payload()   → 直接产出嵌套结构
        ▼
   ┌─────────────┐
   │ 引擎内部表示 │  ← runner.normalize_case() 负责兜底归一
   └─────────────┘
        ▲
        │  DataLoader.load()                → YAML 的「扁平写法」
   YAML / JSON 文件
```

`normalize_case()` 的作用是把「扁平写法」（`method`/`url` 直接挂在用例根上）补齐成「嵌套 `request` 写法」，这样两种来源在 `execute_case()` 里走完全相同的分支。

### 7.2 变量渲染

`{{变量名}}` 占位符在以下位置被渲染：url、headers、params、body、断言期望值、UI 步骤的 selector 与 value。

变量优先级：**命令行 `--var` 覆盖 > 用例内定义 > 文件级 `variables` > 环境配置**。

**安全细节**：变量名中含 `token` / `secret` / `password` / `key` 时，日志里自动打码；请求头中 `authorization` / `cookie` / `x-api-key` / `token` 等敏感头在记录遥测时被替换为掩码（`engine/client.py` 的 `_mask_headers`）。这是为了避免"平台把用户的真实凭据写进报告"这类事故。

### 7.3 前置用例与变量提取

数据驱动的表达能力有限，因此补了两个机制覆盖串联场景：

- **`setup_case`（平台）/ `setup_ref`（CLI）**：声明前置用例。CLI 模式下 `resolve_setup_refs()` 会在内存里把引用展开成内联的前置用例，保证「平台模式」与「CLI 模式」执行行为一致；
- **`extract`**：从响应中按 JSONPath 提取值写入变量上下文，供后续用例通过 `{{变量}}` 引用。典型用法是前置登录用例提取 token。

### 7.4 用例文件加载

`engine/data_loader.py`：

- 按后缀分发 `.yaml` / `.yml` / `.json`；
- 要求根节点是 dict，`variables` 与 `cases` 在类型异常时做兜底；
- `filter_by_tags`（多标签任一命中）、`filter_by_type`、`load_directory`（整目录加载）。

---

## 8. 断言引擎

### 8.1 结构

```
assertions.py
 ├─ 5 类断言：status_code / json_field / response_time / schema / header
 ├─ 13 种操作符：eq ne contains not_contains gt lt ge le empty not_empty in regex length_eq
 ├─ 简化 JSONPath 解析：resolve_json_path() 支持 $.a.b[0].c
 └─ 宽松比较 _loose_equal()：兼容 "1" 与 1、True 与 "true" 这类类型漂移
```

### 8.2 两个设计决策

**① 收集全部失败明细，而不是遇到第一个失败就中断。**
所有断言跑完再统一汇总抛出，异常对象里带全部失败项。理由是：一次执行就应该让人看到所有问题，而不是"修一个跑一次"。

**② 空断言兜底为 `status_code == 200`。**
如果一条用例一个断言都没配，补一个默认断言。否则这条用例会永远绿灯（请求发出去了就算通过），这是比失败更糟糕的假信号。

**③ 宽松比较是有意为之。**
HTTP 世界里的类型漂移极其常见（Query 参数回显成字符串、`true` 与 `True`）。严格比较会让用户大量误报，宽松比较 + `schema` 断言做结构校验是更好的分工。需要严格比较时用 `schema`。

---

## 9. UI 自动化

### 9.1 为什么用 Playwright 同步 API

`engine/ui_actions.py` 使用 `playwright.sync_api`。理由是**与 pytest 的同步用例模型天然契合**——不需要引入 async 插件，也不需要在 sync/async 之间来回转换。每个 `UIPlayer` 实例在生命周期内复用一个浏览器实例。

### 9.2 动作集与失败处理

12 种动作：`open` `click` `input` `select` `hover` `press` `wait` `assert_visible` `assert_text` `assert_value` `assert_url` `screenshot`。

任一动作失败会**立即截图**并抛 `UIActionError`（继承自 `AssertionError`，因此 pytest 会把它当作断言失败而不是错误）。截图落盘为 full-page PNG，路径为 `reports/screenshots/<task_id>/<用例名>_step<序号>_failed.png`，服务层再把它转换成 `/static/screenshots/...` 的 URL 给前端。

### 9.3 浏览器未安装时的可操作性

`ui_actions.py` 在 `sync_playwright()` 启动失败时会抛出带明确指引的错误（提示执行 `playwright install chromium`），而不是抛一个裸的路径不存在异常。这是「面向使用者的错误信息」而非「面向开发者的堆栈」。

---

## 10. AI 子系统

### 10.1 调用方式

用 **OpenAI 官方 SDK** 指向 DeepSeek 的 OpenAI 兼容端点（`DEEPSEEK_BASE_URL`），**同步调用**，客户端延迟创建并缓存，SDK 侧的 `max_retries=0`——重试由服务层自己控制，避免双层重试导致次数翻倍。

三个能力各对应一个提示词文件：

| 能力 | 提示词 | 输出结构 |
| --- | --- | --- |
| 生成用例 | `prompts/generate_cases.md` | 强制输出单个 JSON `{cases:[...]}`（`json_mode=True`） |
| 失败归因 | `prompts/failure_analysis.md` | `{category, summary, reasons, suggestions}`，分类含「接口缺陷 / 脚本缺陷 / 环境问题 / 用例设计问题」 |
| 报告问答 | `prompts/report_qa.md` | 自然语言（`json_mode=False`） |

### 10.2 降级设计（本项目的重点）

降级有**四条触发路径**：

```
① AI_ENABLED=false          ┐
② AI_MOCK=true              ├─→ settings.ai_available == False → 方法入口直接走规则兜底
③ DEEPSEEK_API_KEY 为空     ┘
④ 调用过程中抛任何异常       ─→ 二次降级，并在 raw 字段回填失败原因
```

**关键在于降级后的输出不是"AI 不可用"这句话**，而是基于真实数据的规则结果：

| 能力 | 规则兜底做了什么 |
| --- | --- |
| 生成用例 | 按接口契约用模板生成基础用例 |
| 失败归因 | 关键词匹配归类（超时 → 环境问题、连接拒绝 → 环境问题、状态码 4xx/5xx → 接口缺陷…） |
| 报告问答 | 真实统计聚合的确定性回答 |

响应里带 `mocked=true` 标记，前端可以据此提示用户。这让「没配 API Key 也能完整演示」和「模型服务抖动不影响平台可用性」同时成立。

### 10.3 成本与稳定性控制

| 手段 | 实现 |
| --- | --- |
| 重试 | `attempts = AI_MAX_RETRIES + 1`，指数退避 `min(2^(n-1), 4)` 秒 |
| 超时 | 客户端 `timeout=AI_TIMEOUT_SECONDS`（默认 30s） |
| 输入截断 | `AI_MAX_LOG_CHARS`（默认 6000）对断言/请求、响应、堆栈**按不同比例分段截断**——堆栈给得最多，因为它的定位信息密度最高 |
| 输出限制 | `max_tokens=AI_MAX_TOKENS` |
| 用量记录 | 返回 `prompt_tokens` / `completion_tokens` / `total_tokens` / `elapsed_ms`，路由层打日志 |

### 10.4 输出解析的三层兜底

模型返回的 JSON 常常带多余文本，因此解析按三层递进：**原文直接解析 → 提取 ```json 代码块 → 截取首尾 `{}` 之间**。生成结果再逐条走 Pydantic 校验，坏数据直接丢弃而不是让整个请求失败。

---

## 11. 认证与鉴权

| 环节 | 实现 |
| --- | --- |
| 密码哈希 | bcrypt 加盐，`gensalt(rounds=12)`，显式截断前 72 字节（bcrypt 的输入上限，不截断会静默出错） |
| 令牌 | JWT HS256，载荷含 `sub`(用户名) + `role` + `iat` + `exp` |
| 令牌校验 | `HTTPBearer(auto_error=False)` —— **关掉自动报错，自己抛 401**，以保证错误响应体格式统一 |
| 失败语义 | 未带令牌 / 令牌无效 / 用户不存在 → 401；账号被禁用 → 403 |
| 默认管理员 | 首次启动 `bootstrap()` 幂等创建，用户名密码来自配置 |

### 关于权限模型（重要）

`UserRole`（admin / member）与 `AdminUser` / `get_current_admin` 依赖**已经就绪但未被任何路由使用**。也就是说，当前所有业务接口只要求「已登录」，**没有路由级的权限隔离**，注册接口固定写入 `member` 角色。

这是一处明确的技术债：基础设施铺好了，但没有实际接线。若要启用，只需在需要管理员的路由上把 `CurrentUser` 换成 `AdminUser` 即可——这也是把它保留在代码里而不是删掉的原因。

---

## 12. 定时调度

```
APScheduler BackgroundScheduler
  · timezone = Asia/Shanghai
  · job_defaults = { coalesce: True, max_instances: 1, misfire_grace_time: 300 }
  · 不配置持久化 jobstore
```

**不持久化 jobstore 是有意的**：数据库才是唯一事实来源，每次应用启动都会从 `test_suites` 表全量重建任务（`reload_jobs()`）。这样避免了"数据库改了但 jobstore 还是旧的"这类状态不一致问题，也让部署时不需要额外的持久化卷。

绑定方式：创建 / 更新 / 删除用例集时调 `scheduler_service.sync_suite(suite_id)`，job id 为 `suite_{id}`。cron 表达式用 `CronTrigger.from_crontab`，**要求标准 5 段格式**，格式校验在 schema 层完成（避免非法表达式污染调度器）。

生命周期：`app/main.py` 的 lifespan 中 `start()` 与 `shutdown(wait=False)`。两者都做了异常兜底——**调度器启动失败只记日志，不影响服务启动**，因为手工执行仍然是可用的。

触发链路：`trigger_suite()` 会创建一条 `trigger_type=schedule` 的正常任务（与手工执行完全同链路）并另起线程执行，同时更新 `suite.last_run_at`。**调度器不自建一套执行逻辑**，这是避免逻辑分叉的关键。

---

## 13. 报告与产物

### 13.1 统计聚合

`report_service.py` 负责首页所需的全部统计：概览卡片、通过率趋势（按天补全空白日期，避免折线断点）、项目维度分布、失败用例 TOP N、任务状态分布、最近任务。

**一个为了实现一致性而做的妥协**：失败用例分布需要在 `result_detail` 这个大 JSON 列上做应用层聚合。为跨库一致（SQLite 与 MySQL 的 JSON 函数差异较大），代码只扫描**最近 100 个任务**后在 Python 里聚合，而不写依赖 JSON 函数的 SQL。代价是统计口径受限于最近 100 个任务，收益是不必为数据库差异写两套 SQL。

### 13.2 Allure

- 执行时 `--alluredir=reports/allure-results/<task_no>` 产出原始结果；
- 任务结束后调 `allure generate <results> -o reports/allure-report/<task_no> --clean`（超时 120s）；
- 命令名兼容 `allure` / `allure.bat`；
- **生成失败只记日志，不影响任务状态**——Allure 是增强项，不该让任务因为环境缺 Java 而变红；
- 开关：`ALLURE_AUTO_GENERATE`。

`engine/allure_helper.py` 对 `allure` 包做了 try-import，不可用时所有函数降级为 no-op（`step()` 上下文管理器降级成普通代码块）。因此**引擎层在没有安装 allure-pytest 的环境里依然可以运行**，这同样是"引擎零 Web 依赖"思路的延伸。

### 13.3 产物暴露与截断

| 产物 | URL | 截断策略 |
| --- | --- | --- |
| 失败截图 | `/static/screenshots/<task_id>/...` | 无 |
| Allure HTML | `/static/allure/<task_no>/index.html` | 无 |
| 执行 stdout | 任务详情里的 `stdout_tail` | 截断到 8000 字符 |
| 完整日志 | `GET /tasks/{id}/log` | 单次最多 200000 字符并置 `truncated` 标记 |

只 mount 了 `screenshots` 与 `allure-report` 两个子目录，**而不是把整个 `reports/` 暴露成静态目录**——后者会把日志文件也一并公开。

---

## 14. 配置与日志

### 14.1 配置

全部配置收敛在 `app/config.py`，其他模块一律 `from app.config import settings`，**禁止散落 `os.getenv`**。这是有意的约束：环境变量的来源与默认值只有一处，便于审计与文档化。

- 通过 `pydantic-settings` 从 `.env` 读取，`extra="ignore"`、`case_sensitive=False`；
- 单例由 `lru_cache(maxsize=1)` 保证；
- **SQLite 路径强制解析为绝对路径**（相对路径基于项目根），避免"从不同工作目录启动就连到不同数据库"这个隐蔽 bug；
- 派生属性（`database_url`、`ai_available`、`reports_dir` 等）把「配置 → 行为」的推导集中在一处。

### 14.2 日志

```python
logger = get_logger(__name__)   # 包一层 loguru
```

- 按天切割：`app_{time:YYYY-MM-DD}.log`，保留 `LOG_RETENTION_DAYS` 天；
- 控制台彩色输出，文件不含颜色码；
- 请求耗时通过中间件记录并回写 `X-Process-Time-Ms` 响应头；
- 静态资源与文档请求不记日志——避免噪音淹没真实业务请求。

---

## 15. 前端架构

### 15.1 状态管理

两个 Pinia store，职责刻意分离：

| Store | 管什么 | 持久化 |
| --- | --- | --- |
| `useUserStore` | `token`、`userInfo`、`isLoggedIn`、`isAdmin` | `localStorage`：`atp_token` / `atp_user` |
| `useProjectStore` | 项目列表、`currentProjectId`、`currentProject` | `localStorage`：`atp_current_project_id` |

`currentProjectId` 是「用例 / 用例集 / 执行历史 / 环境配置」四类页面的**统一上下文**——切换项目即切换这些页面的数据源。把它放进 store 而不是 URL 参数，是为了让用户切页面时上下文不丢。

### 15.2 请求层

`web/src/api/request.ts` 统一处理三件事：

- **鉴权**：请求拦截器注入 `Authorization: Bearer <token>`；
- **失效处理**：响应拦截器遇 401 清 token 并跳登录页；
- **错误提示**：把后端统一错误体的 `message` 取出来提示；422 校验失败则把 `data.errors` 拼成可读文案。

对外暴露泛型的 `httpGet / httpPost / httpPut / httpDelete` 与 `pruneParams`（清掉 undefined/null 的查询参数）。

### 15.3 契约对齐

`web/src/types/index.ts` 明确声明「与后端 `app/schemas` 严格对齐」。这是一个**需要人工维护的契约**，也是双端类型不同步的风险点——例如前端 `TriggerType` 的字面量（`manual | schedule | suite | retry`）与后端实际值（`manual | schedule | ci`）已经不一致。彻底解决需要引入 OpenAPI 代码生成（后端已经暴露 `/openapi.json`，具备条件），当前属于已知缺口。

### 15.4 路由与构建

- 路由：`/login`、`/`(Dashboard)、`/projects`、`/cases`、`/suites`、`/tasks`、`/environments`，通配重定向到 `/`；
- 全局守卫负责：设置页面标题、未登录跳登录、已登录访问登录页回首页、缺 userInfo 时 `fetchMe()` 校正（处理"本地有 token 但用户信息丢了"的情况）；
- 使用 `createWebHistory`，因此生产部署必须有 SPA 回退（`web/nginx.conf` 已配 `try_files ... /index.html`）；
- 构建时把 echarts / element-plus / vue 拆成独立 chunk，避免单包过大。

---

## 16. 扩展点

按"改动成本从低到高"排列：

| 扩展点 | 位置 | 说明 |
| --- | --- | --- |
| 启用路由级 RBAC | `app/deps.py` 已有 `AdminUser` | 把需要管理员的路由的 `CurrentUser` 换成 `AdminUser` 即可 |
| 任务内并行 | `PYTEST_MAX_WORKERS` 配置已存在 | 需要把 `CaseTelemetry` 改造成跨进程可回传（如按用例分文件落盘）后再接 xdist |
| 引擎结果回写平台 | `TriggerType.CI` 已定义 | 需要一个"外部执行结果回写"的接口，用于把 CI 里跑的引擎结果同步到平台 |
| 数据库迁移 | `app/database.py` 已留注释 | 接入 Alembic |
| 容器化部署 | `web/nginx.conf` 已按容器名配置 | 补 `Dockerfile` 与 `docker-compose.yml` |
| 性能测试 | `locust` 已在依赖里 | 新增 `engine/performance/` 与对应 `case_type` |
| 前端类型契约自动化 | `/openapi.json` 已暴露 | 用 OpenAPI generator 生成前端类型，消除手工同步 |
| 新增断言类型 | `engine/assertions.py` | 加一个分支 + 在 schema 的字面量里加一个值（两处都要改） |
| 新增 UI 动作 | `engine/ui_actions.py` | 加动作名 + 在 `_execute()` 的分派里加分支（两处都要改） |

---

## 17. 已知技术债汇总

| # | 问题 | 影响 | 位置 |
| --- | --- | --- | --- |
| 1 | `AdminUser` 依赖未被任何路由使用 | 无路由级权限隔离，所有登录用户权限相同 | `app/deps.py` |
| 2 | `PYTEST_MAX_WORKERS` 定义未引用 | 大用例集只能串行，耗时线性增长 | `app/config.py` |
| 3 | `TriggerType.CI` 无赋值入口 | 无法区分"CI 触发的执行" | `app/models/task.py` |
| 4 | 前端 `TriggerType` 与后端不一致 | 字段仅用于展示，暂未引发功能问题 | `web/src/types/index.ts` |
| 5 | 报告统计只扫最近 100 个任务 | 失败分布不是全量口径 | `app/services/report_service.py` |
| 6 | 缺少容器编排文件 | 无法一键部署，nginx 上游指向的 `backend` 无从解析 | 仓库根目录 |
| 7 | 前端类型靠手工与后端对齐 | 契约漂移风险 | `web/src/types/index.ts` |
| 8 | 演示用例依赖境外公有服务（httpbin / saucedemo） | 无法纳入 CI 做稳定回归，只能手工或定时跑 | `data/*.yaml` |

---

## 18. 变更指南：新功能该加在哪一层

| 你想做的事 | 该改哪里 | 不该改哪里 |
| --- | --- | --- |
| 新增一种断言 / 新的请求发送方式 | `engine/assertions.py` / `engine/client.py` | 不要动 `app/` |
| 新增一种 UI 动作 | `engine/ui_actions.py` | 不要动 `app/` |
| 新增一个业务接口 | `app/api/*.py`（路由）+ `app/services/*.py`（逻辑） | 不要在路由里写业务逻辑 |
| 新增一张表 / 字段 | `app/models/` + `app/schemas/` + 前端 `types/index.ts`（三处同步） | — |
| 新增一个配置项 | 只在 `app/config.py` 加字段 + 同步 `.env.example` | 不要在业务代码里 `os.getenv` |
| 改执行行为（并发、超时、重跑） | `app/services/test_runner.py` + `engine/runner.py` | 注意不要破坏文件契约的字段结构 |
| 改结果收集逻辑 | `testcases/conftest.py` | **绝不能 import `app/`** |

---

## 相关文档

- [README.md](README.md) —— 快速开始、配置表、用例编写指南、面试常见问题
- [.github/workflows/ci.yml](.github/workflows/ci.yml) —— CI 流水线与"为什么不跑演示用例"的说明
- [.env.example](.env.example) —— 全部环境变量
