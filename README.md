# auto-test-platform

> 接口测试 + UI 测试 + AI 辅助一体化的 Web 测试管理平台。
> FastAPI + Vue 3 + pytest + DeepSeek，**引擎层可脱离 Web 独立运行**。

把「写用例 → 编排执行 → 看报告 → 定位失败原因」这条链路收进一个平台：
用例是数据而不是代码，执行是独立的 pytest 子进程，失败分析交给大模型做，模型不可用时自动降级为规则兜底。

---

## 目录

- [这个项目解决什么问题](#这个项目解决什么问题)
- [核心能力](#核心能力)
- [技术栈](#技术栈)
- [架构总览](#架构总览)
- [目录结构](#目录结构)
- [快速开始](#快速开始)
- [配置说明](#配置说明)
- [如何新增一个自定义用例](#如何新增一个自定义用例)
- [断言类型速查](#断言类型速查)
- [演示数据说明](#演示数据说明)
- [测试与持续集成](#测试与持续集成)
- [已知限制与后续演进](#已知限制与后续演进)
- [面试常见问题](#面试常见问题)
- [相关文档](#相关文档)

---

## 这个项目解决什么问题

自动化测试项目常见的三个断点：

1. **用例散落在代码里**：新增一条用例要改 Python、提交代码、跑 CI，业务同学完全无法参与。
2. **执行与平台强耦合**：本地调试需要起一整套 Web 服务 + 数据库，CI 里想只跑用例很别扭。
3. **失败定位靠人肉**：报告只告诉你「断言失败」，至于为什么失败、是接口问题还是用例写错了，得自己翻日志。

本项目的三个对应设计：

- **用例即数据**：用例存在 YAML 或数据库里，靠 `pytest.mark.parametrize` 动态参数化成 N 条独立测试项，新增用例零代码改动。
- **引擎层零 Web 依赖**：`engine/` 不 import `app/` 的任何模块，既能被平台调度，也能用 `python run_engine.py --file xxx.yaml` 直接在任意 CI 里跑。
- **AI 参与失败归因**：把失败用例的请求 / 响应 / 断言明细 / 堆栈脱敏后交给 DeepSeek，输出「接口缺陷 / 脚本缺陷 / 环境问题 / 用例设计问题」的分类结论与修复建议；没配 API Key 时降级为基于真实数据的规则兜底，功能不塌陷。

---

## 核心能力

| 模块 | 能力 |
| --- | --- |
| 项目 / 环境管理 | 多项目隔离；每个项目下可配多套环境（base_url、公共 Header、全局变量、超时、SSL 校验），支持默认环境 |
| 用例管理 | 接口用例（method/url/headers/params/body/form/断言）与 UI 用例（步骤式）统一管理，支持标签、前置用例、变量提取 |
| 用例集与调度 | 用例集可绑定环境与 5 段 cron 表达式，后台 APScheduler 定时触发；支持失败重跑次数配置 |
| 执行编排 | 任务级并发（默认上限 4），每个任务一个独立 pytest 子进程，支持超时强杀、失败重跑、整任务重跑 |
| 报告 | 通过率趋势、项目分布、失败用例 TOP N、任务状态分布；可生成 Allure HTML 报告；UI 失败自动截图 |
| AI 辅助 | ① 按自然语言描述生成用例 ② 失败根因分析 ③ 基于统计数据的报告问答；三者均可 Mock 降级 |
| 认证 | JWT（HS256）+ bcrypt 加盐哈希，首次启动自动创建默认管理员 |
| 引擎 CLI | `run_engine.py` 支持按文件 / 标签 / 类型筛选、覆盖变量、失败重跑、生成 Allure 结果 |

---

## 技术栈

**后端**：FastAPI 0.115 · SQLAlchemy 2.0 · Pydantic 2.10 · pydantic-settings · Uvicorn · APScheduler · loguru
**测试引擎**：pytest 8.3 · pytest-rerunfailures · Playwright（同步 API）· httpx · jsonschema · PyYAML · allure-pytest
**AI**：openai SDK 1.59（指向 DeepSeek 的 OpenAI 兼容端点，默认模型 `deepseek-v4`）
**前端**：Vue 3.5 · TypeScript 5.7 · Vite 6 · Element Plus · Pinia · Vue Router · ECharts · axios
**数据**：SQLite（开箱即用）／MySQL（PyMySQL，改一个配置项即可切换）
**工程化**：ruff · black · pre-commit · GitHub Actions

---

## 架构总览

三层结构，**依赖方向单向向下**：`web → app → engine`，`engine` 不知道 `app` 的存在。

```
┌──────────────────────────────────────────────────────────────┐
│  web/   Vue 3 SPA                                            │
│  用例管理 / 用例集 / 执行历史 / 报告 / 环境配置 / AI 助手        │
└───────────────────────────┬──────────────────────────────────┘
                            │ HTTP（Bearer Token）
                            │ 成功直接返回数据体；失败返回 {success,code,message,data}
┌───────────────────────────▼──────────────────────────────────┐
│  app/   FastAPI 服务层                                        │
│                                                              │
│  api/       路由：只做参数声明与依赖注入，不写业务逻辑           │
│  services/  业务：执行编排 / 报告聚合 / AI / 调度 / 演示数据      │
│  models/    ORM：6 张表                                       │
│  schemas/   Pydantic：出入参契约（前端类型与之严格对齐）         │
│  deps.py    依赖注入：会话 / 当前用户 / 分页 / 项目归属校验       │
└───────────────────────────┬──────────────────────────────────┘
                            │ 单向依赖：app → engine（engine 从不反向 import）
                            │ 契约：CaseTelemetry + 结果 JSON 文件
┌───────────────────────────▼──────────────────────────────────┐
│  engine/   测试引擎层（纯 Python，无任何 Web 框架依赖）          │
│                                                              │
│  runner.py      用例执行内核 + PytestRunner（子进程编排）        │
│  client.py      httpx 接口客户端（变量渲染、敏感头脱敏）          │
│  ui_actions.py  Playwright 同步 API 封装（12 种动作）            │
│  assertions.py  5 类断言 + 13 种操作符                          │
│  data_loader.py YAML/JSON 用例加载与筛选                        │
│  allure_helper.py Allure 可选依赖（不可用时全部 no-op）          │
└───────────────────────────┬──────────────────────────────────┘
                            │ 通过子进程启动
┌───────────────────────────▼──────────────────────────────────┐
│  testcases/  pytest 运行期入口                                 │
│  conftest.py            结果收集插件（引擎与服务层唯一契约点）    │
│  test_dynamic_cases.py  把平台下发的用例参数化成 N 条测试项       │
└──────────────────────────────────────────────────────────────┘
```

**唯一契约点**：`app` 与 `engine` 之间不通过函数调用传递结果，而是：

1. `app` 把 `{task_id, env, cases}` 写成 JSON，路径通过 `ATP_CASE_FILE` 传给子进程；
2. `engine` 在进程内用 `CaseTelemetry` 记录请求 / 响应 / 断言 / 截图明细；
3. `testcases/conftest.py` 的 pytest 钩子在会话结束时把结果写进 `ATP_RESULT_FILE`；
4. `app` 读回该 JSON，落库、渲染报告、喂给 AI。

`testcases/conftest.py` 顶部有一句硬约束注释：**它不能 import `app/` 下的任何模块**，否则引擎层就无法脱离 Web 独立运行了。这条约束是整个分层设计的地基。

更详细的设计说明见 [ARCHITECTURE.md](ARCHITECTURE.md)。

---

## 目录结构

```
auto-test-platform/
├── app/                          # FastAPI 服务层
│   ├── api/                      # 路由（auth/projects/environments/testcases/testsuites/tasks/dashboard/ai）
│   ├── models/                   # ORM：users / projects / environments / test_cases / test_suites / tasks
│   ├── schemas/                  # Pydantic 出入参契约
│   ├── services/
│   │   ├── test_runner.py        # 执行编排：任务级并发 + pytest 子进程 + 结果落库
│   │   ├── report_service.py     # 统计聚合与报告数据
│   │   ├── ai_service.py         # DeepSeek 调用 + 规则降级
│   │   ├── scheduler.py          # APScheduler 用例集定时调度
│   │   ├── seed.py               # 首次启动的演示数据初始化
│   │   └── prompts/              # AI 提示词（生成用例 / 失败分析 / 报告问答）
│   ├── utils/                    # JWT、bcrypt、loguru 日志
│   ├── config.py                 # 全局配置唯一入口（pydantic-settings）
│   ├── database.py               # 引擎与会话
│   ├── deps.py                   # 依赖注入
│   └── main.py                   # 应用装配（只做装配，不写业务）
├── engine/                       # 测试引擎层（可脱离 Web 独立运行）
├── testcases/                    # pytest 运行期入口与结果收集插件
├── web/                          # Vue 3 前端
│   ├── src/{api,components,router,stores,types,utils,views}
│   └── nginx.conf                # 生产部署用的反代与 SPA 回退配置
├── data/                         # 内置演示用例（httpbin / saucedemo）
├── reports/                      # 运行时产物：日志、Allure、失败截图（不入库）
├── .github/workflows/ci.yml      # 持续集成流水线
├── run_engine.py                 # 引擎层独立命令行入口
├── pyproject.toml                # ruff / black / pytest 配置
├── requirements.txt
├── .env.example                  # 环境变量样板
└── .pre-commit-config.yaml
```

---

## 快速开始

### 环境要求

- Python **3.11+**（推荐 3.12）
- Node **18.18+**（推荐 20 LTS）+ pnpm **9**
- 可选：Java + Allure CLI（仅当需要生成 Allure HTML 报告时）

### 1. 后端

```bash
git clone https://github.com/fyb580231/auto-test-platform.git
cd auto-test-platform

python -m venv .venv
# Windows: .venv\Scripts\activate
source .venv/bin/activate

pip install -r requirements.txt

# 复制配置样板（.env 已被 .gitignore 忽略）
cp .env.example .env

# 启动服务
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

启动后：

- 接口文档：http://127.0.0.1:8000/docs
- 健康检查：http://127.0.0.1:8000/api/health
- 默认账号：**admin / admin123**（首次启动自动创建，生产环境务必修改）

首次启动会自动建表、写入演示项目 / 环境 / 用例 / 用例集，并启动定时调度器。

### 2. 前端

```bash
cd web
pnpm install
pnpm dev          # 开发服务器，已把 /api 与 /static 代理到 127.0.0.1:8000
```

浏览器打开 http://localhost:5173 即可。

生产构建：

```bash
pnpm build        # 先 vue-tsc --noEmit 做类型检查，再 vite build 输出到 web/dist
```

`web/nginx.conf` 已备好 SPA 回退与 `/api/`、`/static/` 的反向代理（默认指向容器名 `backend`，按实际部署环境调整）。

### 3. 引擎层 CLI（不启动 Web）

这是引擎层可独立运行的最直接体现——**不起 FastAPI、不连数据库**：

```bash
# 跑一个 YAML 用例文件里的全部用例
python run_engine.py --file data/demo_api_cases.yaml

# 只跑 smoke 标签
python run_engine.py --file data/demo_api_cases.yaml --tags smoke

# 只跑 UI 用例、失败重跑 1 次、并生成 Allure 结果
python run_engine.py --file data/demo_ui_cases.yaml --type ui --retry 1 --allure

# 命令行覆盖变量（不改动用例文件）
python run_engine.py --file data/demo_api_cases.yaml --var base_url=https://httpbin.org

# 查看全部参数
python run_engine.py --help
```

> 跑 UI 用例前需要先装浏览器内核：`playwright install chromium`

### 4. 演示数据里有一条"故意失败"的用例

`data/demo_api_cases.yaml` 中的 `api_010` 会断言一个响应里不存在的字段 `$.business_code`，**它必然会失败**。这不是 bug，而是为了让「失败报告 + UI 截图 + AI 失败归因」这三块能力有真实的失败样本可看。演完删掉即可。

---

## 配置说明

全部配置收敛在 `app/config.py` 一个模块，其他代码一律 `from app.config import settings`，**禁止在各处散落 `os.getenv`**——环境变量的来源与默认值只有一处，便于审计与文档化。配置从 `.env` 读取（`extra="ignore"`，大小写不敏感）。

| 分类 | 变量 | 默认值 | 说明 |
| --- | --- | --- | --- |
| 应用 | `APP_NAME` | `auto-test-platform` | 应用名称 |
| | `APP_VERSION` | `1.0.0` | 版本号 |
| | `DEBUG` | `false` | 开启后 500 响应会带真实错误信息 |
| | `HOST` / `PORT` | `0.0.0.0` / `8000` | 监听地址与端口 |
| | `CORS_ORIGINS` | `http://localhost:5173,http://localhost:8080` | 逗号分隔的跨域白名单 |
| 数据库 | `DB_TYPE` | `sqlite` | `sqlite` 或 `mysql` |
| | `SQLITE_PATH` | `./data/auto_test_platform.db` | SQLite 文件路径（相对路径按项目根解析） |
| | `MYSQL_HOST` / `MYSQL_PORT` | `127.0.0.1` / `3306` | MySQL 连接信息 |
| | `MYSQL_USER` / `MYSQL_PASSWORD` / `MYSQL_DATABASE` | `root` / 空 / `auto_test_platform` | MySQL 库信息 |
| 认证 | `JWT_SECRET` | `dev-only-secret-please-change` | **生产必须替换** |
| | `JWT_ALGORITHM` | `HS256` | 签名算法 |
| | `JWT_EXPIRE_MINUTES` | `1440` | 令牌有效期（分钟） |
| 管理员 | `DEFAULT_ADMIN_USERNAME` / `DEFAULT_ADMIN_PASSWORD` | `admin` / `admin123` | 首次启动自动创建 |
| AI | `DEEPSEEK_API_KEY` | 空 | 留空则 AI 模块自动降级为 Mock |
| | `DEEPSEEK_BASE_URL` | `https://api.deepseek.com` | OpenAI 兼容端点 |
| | `DEEPSEEK_MODEL` | `deepseek-v4` | 无 v4 权限时改成 `deepseek-chat` 即可 |
| | `AI_ENABLED` / `AI_MOCK` | `true` / `false` | 总开关与强制 Mock 开关 |
| | `AI_TIMEOUT_SECONDS` | `30` | 单次请求超时 |
| | `AI_MAX_RETRIES` | `2` | 服务层重试次数（指数退避） |
| | `AI_MAX_TOKENS` | `4096` | 单次生成上限 |
| | `AI_MAX_LOG_CHARS` | `6000` | 失败分析送入模型的最大日志字符数（成本控制） |
| 执行引擎 | `PYTEST_TIMEOUT_SECONDS` | `300` | 单任务执行超时，超时强制终止 |
| | `DEFAULT_RETRY_TIMES` | `2` | 用例默认失败重跑次数 |
| | `MAX_CONCURRENT_TASKS` | `4` | 同时执行的任务数上限 |
| | `PYTEST_MAX_WORKERS` | `1` | 预留：任务内并行度（当前未接线） |
| | `ALLURE_AUTO_GENERATE` | `true` | 是否自动生成 Allure HTML |
| | `ALLURE_COMMAND` | `allure` | Allure CLI 命令名 |
| 日志 | `LOG_LEVEL` | `INFO` | 日志级别 |
| | `LOG_DIR` | `./reports/logs` | 日志目录，按天切割 |
| | `LOG_RETENTION_DAYS` | `14` | 日志保留天数 |

派生属性（只读，由上述配置算出）：`database_url`、`cors_origin_list`、`is_sqlite`、`ai_available`、`sqlite_file_path`、`reports_dir`、`logs_dir`、`data_dir`。

---

## 如何新增一个自定义用例

### 方式一：在平台上建（推荐日常使用）

1. 在「项目管理」里创建项目，在「环境配置」里配好目标环境的 `base_url`；
2. 进入「用例管理」→ 新建用例，选择类型（接口 / UI）；
3. 接口用例填 method / url / headers / params / body，UI 用例填步骤（动作 + 选择器 + 值）；
4. 在断言区配置期望结果；
5. 在「用例集」里勾选该用例，点执行，或直接单条运行。

平台侧的用例字段白名单定义在 `app/api/testcases.py`，模型方法 `TestCase.to_engine_payload()` 负责把 ORM 对象转成引擎能吃的嵌套结构。

### 方式二：写 YAML/JSON 文件（适合纳入代码仓库、走 CI）

用例文件的顶层结构：

```yaml
variables:                      # 文件级变量，可被用例内 {{变量名}} 引用
  base_url: https://httpbin.org
  test_username: test_user_001

cases:
  - id: api_001                              # 唯一 ID（平台内用于定位）
    name: "GET /get - 连通性与 Query 参数回显"   # 可读名称
    case_type: api                           # api | ui
    description: "这条用例在做什么"
    tags: ["smoke", "critical"]              # smoke | regression | critical，可多选
    method: GET
    url: /get                                # 相对路径，与 variables.base_url 拼接
    headers:
      X-Trace-Id: "{{trace_id}}"
    params:
      source: auto_test_platform
      page: 1
    body: { ... }                            # 请求体（JSON）
    form: { ... }                            # 表单（与 body 二选一）
    extract:                                 # 从响应里提取变量，供后续用例引用
      token: "$.data.token"
    assertions:
      - type: status_code
        expected: 200
        name: "状态码 200"
      - type: json_field
        field: "$.args.source"
        op: eq
        expected: auto_test_platform
        message: "Query 参数 source 未被服务端正确接收"
```

UI 用例把 `method/url` 换成 `base_url` + `steps`：

```yaml
  - id: ui_001
    name: "登录成功"
    case_type: ui
    base_url: https://www.saucedemo.com
    steps:
      - action: open
        url: /
      - action: input
        selector: "#user-name"
        value: "{{test_username}}"
      - action: input
        selector: "#password"
        value: "{{test_password}}"
      - action: click
        selector: "#login-button"
      - action: assert_url
        expected_contains: inventory
      - action: screenshot          # 需要留痕时显式截图
        name: "登录后首页"
```

**字段要点**：

- `url` 支持相对路径（自动拼 `variables.base_url`）也支持绝对 URL；
- `{{变量}}` 占位符可用于 url / headers / params / body / 断言期望值 / UI 步骤的 selector 与 value；变量来源优先级为「命令行 `--var` 覆盖 > 用例内定义 > 文件级 `variables` > 环境配置」，变量名里含 `token`/`secret`/`password`/`key` 时日志自动打码；
- `setup_ref`（CLI 模式）和 `setup_case`（平台模式）用于声明前置用例，比如先登录拿 token；CLI 会在内存里把 `setup_ref` 展开成内联的前置用例，保证两种模式的执行行为一致；
- 没有配置任何断言时，会兜底断言 `status_code == 200`，避免出现"跑了但没校验"的假绿灯。

**UI 支持的动作**（共 12 种）：

`open` · `click` · `input` · `select` · `hover` · `press` · `wait` · `assert_visible` · `assert_text` · `assert_value` · `assert_url` · `screenshot`

任一 UI 步骤失败会**立即截图**并抛错，截图落在 `reports/screenshots/<task_id>/`，文件名形如 `<用例名>_step<序号>_failed.png`，平台会自动把它转成 `/static/screenshots/...` 的 URL 供前端展示。

**写完之后怎么跑**：

```bash
# 命令行直接验证
python run_engine.py --file ./my_cases.yaml --tags smoke

# 或者把文件放进 data/，重启后端服务，平台会自动加载成演示数据
```

---

## 断言类型速查

`engine/assertions.py` 支持 5 类断言、13 种比较操作符：

| 断言类型 | 作用 | 关键字段 |
| --- | --- | --- |
| `status_code` | HTTP 状态码相等 | `expected` |
| `json_field` | 按简化 JSONPath 取字段后比较 | `field`（如 `$.data.items[0].id`）、`op`、`expected` |
| `response_time` | 响应耗时 ≤ 期望毫秒数 | `expected`（毫秒） |
| `schema` | 用 JSON Schema 校验响应结构 | `expected`（Schema 对象，基于 jsonschema） |
| `header` | 校验响应头 | `field`、`op`、`expected` |

**操作符**：`eq` · `ne` · `contains` · `not_contains` · `gt` · `lt` · `ge` · `le` · `empty` · `not_empty` · `in` · `regex` · `length_eq`

所有断言执行完毕后统一汇总失败明细，抛出的异常里带有全部失败项的完整信息，而不是遇到第一个失败就中断——这样一次执行就能看全所有问题。

> 简化版 JSONPath 支持 `$.a.b[0].c` 这类路径，足够覆盖日常接口断言；不支持的复杂表达式（如递归下降、过滤器）建议直接用 `schema` 断言。

---

## 演示数据说明

首次启动会写入一套开箱即用的演示数据（`app/services/seed.py`）：

- **演示项目** + **两套环境**（开发 / 预发，预发为占位配置）；
- **接口用例** `data/demo_api_cases.yaml`：全部指向 **httpbin.org**，覆盖连通性、参数回显、返回值唯一性、状态码、响应头、JSON Schema、变量提取与前置用例编排等场景；
- **UI 用例** `data/demo_ui_cases.yaml`：全部指向 **saucedemo.com**，覆盖登录、购物车、排序等典型流程；
- **演示用例集**：把上述用例打包，并演示定时触发配置。

演示用例统一把响应时间断言放宽到 10s（httpbin 是境外公有服务，跨网络耗时波动大），**只用于演示"响应时间断言"这个能力，不是真实性能基线**。接入自己的内网服务时，按 SLA 收紧到 500ms 量级即可。

---

## 测试与持续集成

### 用一个细节理解测试结构

项目里**没有传统的 `tests/` 目录**，因为被测对象是"用户配置的用例"，而不是"平台自身的函数"。`testcases/test_dynamic_cases.py` 是一个**空壳入口**：它从 `ATP_CASE_FILE` 读用例并动态参数化，没有该环境变量时用例列表为空。

所以有一个容易踩的坑：

```bash
pytest          # ⚠️ 会全绿，但一条真实用例都没跑（参数为空 → 全部 skip）
```

正确姿势是走引擎层 CLI，它会自动注入载荷文件：

```bash
python run_engine.py --file data/demo_api_cases.yaml --tags smoke
```

### CI 流水线

`.github/workflows/ci.yml` 在 push / PR 到 `main` 时触发，三个并行 job：

| Job | 内容 |
| --- | --- |
| 后端 · 代码风格 | `ruff check .` + `black --check .`（版本与 `.pre-commit-config.yaml` 一致） |
| 后端 · 启动冒烟 | 装依赖 → `from app.main import app` → `run_engine.py --help` → 用 `TestClient` 走完整 lifespan，探活 `/api/health`、验证未登录访问业务接口返回 401、检查 OpenAPI 已注册接口数 |
| 前端 · 类型检查与构建 | `pnpm install --frozen-lockfile` → `pnpm build`（`vue-tsc --noEmit` + `vite build`） |

**CI 刻意不跑 `testcases/` 下的演示用例**，原因写在 workflow 注释里：演示接口用例指向 httpbin.org、UI 用例指向 saucedemo.com，都是境外公有服务，网络抖动会导致与代码无关的红灯；UI 用例还要 `playwright install chromium`，属重量级依赖。**流水线只做"零外部依赖"的验证，保证任何一次提交都能稳定复现。** 演示用例的回归交给引擎层手工或定时执行。

### 本地提交前检查

```bash
pre-commit install       # 装一次即可
pre-commit run --all-files
```

钩子包含：尾随空格、文件末尾换行、YAML/JSON 语法、大文件拦截（>1MB）、合并冲突标记、私钥检测、ruff（带 `--fix`）、black。ruff 只做 lint，格式化统一交给 black，避免两个格式化器互相打架。

---

## 已知限制与后续演进

诚实列出当前项目的边界，避免误用：

| 项 | 现状 | 说明 |
| --- | --- | --- |
| 路由级权限隔离 | **未实现** | `UserRole`（admin/member）与 `AdminUser` 依赖已就绪，但没有任何路由使用它，业务接口目前只要求登录 |
| 用例级并行 | **未实现** | `PYTEST_MAX_WORKERS` 配置项已定义但未接线。原因是进程内遥测（`CaseTelemetry`）依赖同进程收集明细，上 pytest-xdist 后 worker 是独立进程，遥测要跨进程回传会显著增加复杂度。这是**明确的扩展点，不是遗漏** |
| `TriggerType.CI` | **已定义未使用** | 枚举里留了 `ci` 值，但没有赋值入口（`engine` 侧无回写通道），目前只有 `manual` 与 `schedule` 两条路径 |
| 前端 `TriggerType` 字面量 | **与后端不一致** | 前端定义为 `manual \| schedule \| suite \| retry`，后端实际是 `manual \| schedule \| ci`，字段仅用于展示，暂未造成功能问题 |
| 数据库迁移 | **用 `create_all`** | 生产环境如需版本化迁移，可接入 Alembic（`app/database.py` 已留注释） |
| 容器化 | **缺失** | `web/nginx.conf` 反代到容器名 `backend`，暗示预期配合 docker-compose 部署，但仓库里没有 `Dockerfile` 与 `docker-compose.yml` |
| 性能测试 | **仅预留依赖** | `locust` 已列入 `requirements.txt`，代码中无任何引用 |
| 平台侧用例编排能力 | **受限于数据驱动** | 用例是数据，无法写任意 Python 逻辑；复杂场景需要靠 `setup_case` 前置用例 + `extract` 变量提取两个机制组合 |

---

## 面试常见问题

以下 5 个点是这个项目里最值得展开的设计决策，每个都包含「做了什么」与「付出了什么代价」。

### 1. 为什么要把引擎层做成可以脱离 Web 独立运行？

**亮点**：`engine/` 是全项目最干净的模块——它不 import `app/` 的任何东西，不知道数据库、不知道权限、不知道 HTTP。这条边界让同一套执行内核有两条使用路径：平台通过 `PytestRunner` 调度它，CLI 通过 `run_engine.py` 直接调用它。带来的实际收益是：本地调试用例不需要起数据库，接进任意 CI 只需要一个 YAML 文件，引擎层的改动不会波及 Web 层。

**权衡**：为了维持这条边界，`app` 和 `engine` 之间**不能直接传对象**，只能约定一个跨进程契约：结果通过「载荷 JSON 文件进去、结果 JSON 文件出来」+ `ATP_*` 环境变量传递，外加 `testcases/conftest.py` 里一个纯 pytest 钩子做收集。这比直接函数调用麻烦得多，也多了一层序列化开销。另一个代价是同一个概念要在两侧各有一份表示（`TestCase.to_engine_payload()` 与 `engine` 的 `normalize_case()` 都要理解用例结构），存在轻微重复。我判断这是值得的：耦合是长期成本，序列化是一次性成本。

### 2. 执行用例为什么要开独立子进程，而不是 `pytest.main()`？

**亮点**：`engine/runner.py` 用 `subprocess.run([sys.executable, "-m", "pytest", ...])` 起独立进程，而不是在服务进程里调 `pytest.main()`。三个理由：**崩溃隔离**（用例里出现段错误、`os._exit`、C 扩展崩溃时，只死子进程，Web 服务不受影响）；**可被强杀**（`subprocess` 支持超时后终止，线程不行——Python 没法从外部安全地打断一个线程）；**避开 GIL 争抢**（被测逻辑和 Web 服务不互相抢 GIL）。

**权衡**：每次任务都有一次 Python 解释器启动 + pytest 插件加载的固定开销，长尾任务是几十毫秒到几百毫秒量级；而且父子进程之间只能靠文件和环境变量通信，不能直接返回对象。相比之下收益是稳定性和可控性，对一个"跑了就不该拖垮服务"的测试平台来说，这个取舍是明确划算的。

### 3. 并发模型为什么选「任务级并发、任务内串行」？

**亮点**：`test_runner.py` 用模块级 `ThreadPoolExecutor(max_workers=MAX_CONCURRENT_TASKS)` + `BoundedSemaphore` 双保险，默认上限 4。用信号量而不是只靠线程池，是因为同一个任务可能被重复提交（用户连点执行按钮），所以还额外维护了一个 `_RUNNING_TASKS` 集合做去重。受控的并发上限让平台不会因为一次批量执行把自己的机器打满。

**权衡**：任务内串行意味着一个 200 条用例的用例集耗时会线性叠加。**为什么不直接上 `-n` / pytest-xdist？** 因为 `CaseTelemetry` 是在被测进程内记录请求、响应、断言明细的，xdist 的每个 worker 是独立进程，这些明细要回传主进程需要额外的序列化与合并逻辑，会让"引擎层与结果收集"这条本来很干净的链路复杂一大截。所以我把并行度作为**显式配置项 `PYTEST_MAX_WORKERS` 预留**，而不是偷偷实现一个半成品——留一个明确的扩展点，比留一个隐藏的坑更好。

### 4. AI 能力为什么设计成「可降级」而不是「可选」？

**亮点**：三种情况都会触发降级——`AI_ENABLED=false`、`AI_MOCK=true`、或 `DEEPSEEK_API_KEY` 为空；而且**调用过程中抛任何异常也会二次降级**。关键是降级后不是返回一句"AI 不可用"，而是返回**基于真实数据的规则结果**：生成用例走模板、失败归因走关键词匹配、报告问答走真实统计聚合，只是响应里带上 `mocked=true` 标记。这让"没配 API Key 的人 clone 下来也能完整演示所有功能"成为可能，也让模型服务的抖动不会传导成平台功能不可用。

**权衡**：要维护两套实现，`ai_service.py` 里 LLM 路径 + 规则兜底路径让文件规模翻了一倍，且两条路径的输出结构必须严格一致才能被同一套 schema 接住。另外成本控制也要自己兜：`AI_MAX_LOG_CHARS` 对断言/请求、响应、堆栈**分段按不同比例截断**（堆栈给得最多，因为定位信息密度最高），配合 `max_tokens` 限制与 token 用量记录。换来的是"演示零门槛 + 生产抗抖动"，我认为这个代价是必要的。

### 5. 为什么坚持「用例是数据，不是代码」？

**亮点**：`testcases/test_dynamic_cases.py` 整个文件只有一个 `pytest.mark.parametrize("case", _CASES)`——平台把用例序列化成 JSON 载荷，pytest 把它参数化成 N 条独立测试项。这一步换来了三件事：新增用例**零代码改动**（不懂 Python 的业务同学也能加用例）；每条用例天然拥有**独立的结果、耗时、重跑次数**，互不污染；"按标签筛选""单条重跑""失败重跑"这些需求全部退化成**参数问题**，不需要任何额外的调度代码。顺带一个好处：默认 `pytest` 因为没有载荷文件会一条都不跑，这是**刻意的**——它保证了没人能误以为"平台自身的 pytest 通过"就等于"用户的用例通过"。

**权衡**：表达能力受限。用例是数据就意味着不能写任意 Python 逻辑，于是才必须补上 `setup_case`（前置用例编排）和 `extract`（响应变量提取）两个机制来覆盖"先登录再查订单"这类串联场景；而一旦有重复逻辑，只能在数据层面重复或靠前置用例复用，无法抽象成函数。`setup_ref` 在 CLI 模式下会被展开成内联用例、在平台模式下由数据库引用解析，也是为了同一份 YAML 在两种模式下行为一致而付出的额外复杂度。

---

## 相关文档

- [ARCHITECTURE.md](ARCHITECTURE.md) —— 分层设计与依赖规则、数据模型、执行时序、契约点、并发模型、扩展点
- [.env.example](.env.example) —— 全部环境变量及其注释
- [.github/workflows/ci.yml](.github/workflows/ci.yml) —— CI 流水线及其设计取舍
- 运行时接口文档：服务启动后访问 `/docs`（Swagger）或 `/redoc`

---

## License

本项目为个人作品集项目，未附带开源许可证。
