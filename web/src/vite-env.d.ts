/// <reference types="vite/client" />

/** 环境变量类型声明（与 .env.development 对齐） */
interface ImportMetaEnv {
  /** 站点标题 */
  readonly VITE_APP_TITLE: string
  /** 接口前缀，默认 /api */
  readonly VITE_API_BASE_URL: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
