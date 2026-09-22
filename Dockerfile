# syntax=docker/dockerfile:1
# ==============================================================================
# 后端镜像：FastAPI 服务 + pytest 执行引擎
#
# 引擎层（engine/）会被服务层以子进程方式调用，因此镜像里同时包含
# 应用代码、pytest 用例入口（testcases/）与内置演示数据（data/）。
#
# 常用构建参数：
#   --build-arg INSTALL_ALLURE=true              装入 Allure CLI（生成 HTML 报告，需 JRE）
#   --build-arg INSTALL_PLAYWRIGHT_BROWSERS=true 装入 Chromium 内核（跑 UI 用例需要）
#   --build-arg PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple  国内网络加速
# ==============================================================================
FROM python:3.12-slim

ARG INSTALL_ALLURE=true
ARG INSTALL_PLAYWRIGHT_BROWSERS=false
ARG PIP_INDEX_URL=""
ARG ALLURE_VERSION=2.46.1

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TZ=Asia/Shanghai

WORKDIR /app

# ------------------------------------------------------------------------------
# 系统依赖
# Allure 的 tar 包只是脚本集合，真正执行 HTML 生成需要 JRE，所以这里用
# default-jre-headless（随 Debian 版本解析到 17 或 21），比写死 jdk 版本更抗基础镜像升级。
# ------------------------------------------------------------------------------
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends ca-certificates curl gzip tar tzdata; \
    if [ "$INSTALL_ALLURE" = "true" ]; then \
        apt-get install -y --no-install-recommends default-jre-headless; \
        curl -fsSL -o /tmp/allure.tgz \
            "https://github.com/allure-framework/allure2/releases/download/${ALLURE_VERSION}/allure-${ALLURE_VERSION}.tgz"; \
        mkdir -p /opt/allure; \
        tar -xzf /tmp/allure.tgz -C /opt/allure --strip-components=1; \
        ln -sf /opt/allure/bin/allure /usr/local/bin/allure; \
        rm -f /tmp/allure.tgz; \
    fi; \
    rm -rf /var/lib/apt/lists/*

# ------------------------------------------------------------------------------
# Python 依赖：单独一层，代码改动不会导致重装依赖
# ------------------------------------------------------------------------------
COPY requirements.txt ./
RUN if [ -n "$PIP_INDEX_URL" ]; then pip config set global.index-url "$PIP_INDEX_URL"; fi; \
    pip install --upgrade pip; \
    pip install -r requirements.txt

# Playwright 浏览器内核体积很大（数百 MB），默认不装。
# 需要执行 UI 用例时用 --build-arg INSTALL_PLAYWRIGHT_BROWSERS=true 打开。
RUN if [ "$INSTALL_PLAYWRIGHT_BROWSERS" = "true" ]; then \
        playwright install --with-deps chromium; \
        rm -rf /var/lib/apt/lists/*; \
    fi

# ------------------------------------------------------------------------------
# 应用代码
# ------------------------------------------------------------------------------
COPY app ./app
COPY engine ./engine
COPY testcases ./testcases
COPY data ./data
COPY run_engine.py pyproject.toml ./

# 运行期目录（reports 通常由 docker-compose 以 volume 挂载覆盖）
RUN mkdir -p reports/logs reports/screenshots reports/allure-results reports/allure-report

EXPOSE 8000

# 单进程足以支撑平台自身的管理流量；用例执行在独立子进程中完成
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
