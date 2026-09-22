# syntax=docker/dockerfile:1
# ==============================================================================
# 前端镜像：多阶段构建
#
# 构建阶段用 Node 产出静态产物，运行阶段只保留 nginx + dist，
# 最终镜像里不含 node_modules 与源码，体积和攻击面都小得多。
#
# 生产环境不存在跨域：nginx 把 /api 与 /static 反代到后端容器（见 nginx.conf）。
# 前端请求的 baseURL 在未注入 VITE_API_BASE_URL 时会回退为 `/api`，
# 因此这里无需额外配置环境变量即可正确工作。
# ==============================================================================

# ---------- 构建阶段 ----------
FROM node:20-alpine AS build

WORKDIR /app

# 锁定 pnpm 大版本，与 CI（pnpm/action-setup@v4, version 9）以及 lockfile v9.0 保持一致
RUN npm install -g pnpm@9

# 先只拷贝依赖清单，命中缓存时无需重复安装
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

COPY . .
RUN pnpm build

# ---------- 运行阶段 ----------
FROM nginx:1.27-alpine

# 用仓库内的 nginx.conf 覆盖默认站点配置（SPA 回退 + 反向代理）
RUN rm -f /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
