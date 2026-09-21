/**
 * 认证相关接口：登录、注册、当前用户、修改密码。
 */
import { httpGet, httpPost } from '@/api/request'
import type {
  ChangePasswordPayload,
  LoginPayload,
  LoginResponse,
  MessageResponse,
  RegisterPayload,
  UserInfo,
} from '@/types'

/** 账号密码登录，返回 JWT 与用户信息 */
export function login(payload: LoginPayload): Promise<LoginResponse> {
  return httpPost<LoginResponse>('/auth/login', payload)
}

/** 注册新用户 */
export function register(payload: RegisterPayload): Promise<UserInfo> {
  return httpPost<UserInfo>('/auth/register', payload)
}

/** 获取当前登录用户（用于刷新页面后恢复用户信息） */
export function fetchCurrentUser(): Promise<UserInfo> {
  return httpGet<UserInfo>('/auth/me')
}

/** 修改当前用户密码 */
export function changePassword(payload: ChangePasswordPayload): Promise<MessageResponse> {
  return httpPost<MessageResponse>('/auth/change-password', payload)
}
