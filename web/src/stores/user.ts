/**
 * 用户状态管理：token、用户信息、登录 / 登出 / 恢复会话。
 *
 * token 与用户信息都持久化到 localStorage：
 * 刷新页面后先用缓存渲染，再由路由守卫调用 `fetchMe()` 校正，避免白屏与状态闪烁。
 */
import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import { changePassword as changePasswordApi, fetchCurrentUser, login as loginApi } from '@/api/auth'
import { clearToken, getToken, setToken } from '@/api/request'
import type { ChangePasswordPayload, LoginPayload, MessageResponse, UserInfo } from '@/types'

/** localStorage 中的用户信息键名 */
const USER_KEY = 'atp_user'

/** 读取本地缓存的用户信息（缓存损坏时返回 null，不影响启动） */
function readCachedUser(): UserInfo | null {
  const raw = localStorage.getItem(USER_KEY)
  if (!raw) return null
  try {
    return JSON.parse(raw) as UserInfo
  } catch {
    return null
  }
}

export const useUserStore = defineStore('user', () => {
  /** 当前 token */
  const token = ref<string>(getToken())
  /** 当前登录用户信息 */
  const userInfo = ref<UserInfo | null>(readCachedUser())

  const isLoggedIn = computed<boolean>(() => Boolean(token.value))
  const isAdmin = computed<boolean>(() => userInfo.value?.role === 'admin')

  /** 写入（或清除）用户信息并同步 localStorage */
  function persistUser(user: UserInfo | null): void {
    userInfo.value = user
    if (user) {
      localStorage.setItem(USER_KEY, JSON.stringify(user))
    } else {
      localStorage.removeItem(USER_KEY)
    }
  }

  /** 登录：保存 token 与用户信息 */
  async function login(payload: LoginPayload): Promise<void> {
    const result = await loginApi(payload)
    token.value = result.access_token
    setToken(result.access_token)
    persistUser(result.user)
  }

  /** 拉取当前用户信息（刷新页面后校正本地缓存） */
  async function fetchMe(): Promise<UserInfo | null> {
    if (!token.value) return null
    const user = await fetchCurrentUser()
    persistUser(user)
    return user
  }

  /** 退出登录：清理本地登录态 */
  function logout(): void {
    token.value = ''
    clearToken()
    persistUser(null)
  }

  /** 修改密码 */
  function changePassword(payload: ChangePasswordPayload): Promise<MessageResponse> {
    return changePasswordApi(payload)
  }

  return {
    token,
    userInfo,
    isLoggedIn,
    isAdmin,
    login,
    fetchMe,
    logout,
    changePassword,
  }
})
