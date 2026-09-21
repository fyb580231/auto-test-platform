<!--
  App.vue —— 应用主框架。

  职责：
  1. `/login` 等 `meta.public` 页面独立渲染，不套主框架；
  2. 其余页面渲染为「左侧可折叠菜单 + 顶部面包屑 + 内容区」布局；
  3. 顶部常驻展示当前项目，未选择项目时提示前往「项目管理」；
  4. 右上角用户下拉提供「修改密码 / 退出登录」。
-->
<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from 'element-plus'
import {
  ArrowDown,
  DataAnalysis,
  Document,
  Expand,
  Fold,
  Folder,
  HomeFilled,
  Setting,
  SwitchButton,
  Tickets,
  User,
} from '@element-plus/icons-vue'
import type { Component } from 'vue'

import { useProjectStore } from '@/stores/project'
import { useUserStore } from '@/stores/user'
import type { ChangePasswordPayload } from '@/types'

/** 侧边栏菜单项 */
interface MenuItem {
  path: string
  title: string
  icon: Component
}

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()
const projectStore = useProjectStore()

const menus: MenuItem[] = [
  { path: '/', title: '首页', icon: HomeFilled },
  { path: '/projects', title: '项目管理', icon: Folder },
  { path: '/cases', title: '用例管理', icon: Document },
  { path: '/suites', title: '用例集', icon: Tickets },
  { path: '/tasks', title: '执行历史', icon: DataAnalysis },
  { path: '/environments', title: '环境配置', icon: Setting },
]

/** 侧边栏是否折叠 */
const isCollapse = ref(false)
/** 是否为独立布局页面（登录页） */
const isStandalone = computed(() => route.meta.public === true)
/** 当前高亮菜单 */
const activeMenu = computed(() => route.path)

/* ------------------------------- 修改密码 ------------------------------- */
const passwordVisible = ref(false)
const passwordSubmitting = ref(false)
const passwordFormRef = ref<FormInstance>()
const passwordForm = reactive({
  old_password: '',
  new_password: '',
  confirm_password: '',
})

const passwordRules: FormRules<typeof passwordForm> = {
  old_password: [{ required: true, message: '请输入原密码', trigger: 'blur' }],
  new_password: [
    { required: true, message: '请输入新密码', trigger: 'blur' },
    { min: 6, max: 128, message: '新密码长度需为 6-128 位', trigger: 'blur' },
  ],
  confirm_password: [
    { required: true, message: '请再次输入新密码', trigger: 'blur' },
    {
      validator: (_rule, value: string, callback: (error?: Error) => void) => {
        if (value !== passwordForm.new_password) {
          callback(new Error('两次输入的新密码不一致'))
          return
        }
        callback()
      },
      trigger: 'blur',
    },
  ],
}

/** 打开修改密码对话框并重置表单 */
function openPasswordDialog(): void {
  passwordForm.old_password = ''
  passwordForm.new_password = ''
  passwordForm.confirm_password = ''
  passwordVisible.value = true
}

/** 提交修改密码 */
async function submitPassword(): Promise<void> {
  if (!passwordFormRef.value) return
  const valid = await passwordFormRef.value.validate().catch(() => false)
  if (!valid) return

  passwordSubmitting.value = true
  try {
    const payload: ChangePasswordPayload = {
      old_password: passwordForm.old_password,
      new_password: passwordForm.new_password,
    }
    const result = await userStore.changePassword(payload)
    ElMessage.success(result.message || '密码修改成功')
    passwordVisible.value = false
  } catch {
    // 错误提示已由 axios 拦截器统一处理
  } finally {
    passwordSubmitting.value = false
  }
}

/* -------------------------------- 退出登录 ------------------------------- */
async function handleLogout(): Promise<void> {
  try {
    await ElMessageBox.confirm('确认退出当前账号吗？', '退出登录', {
      type: 'warning',
      confirmButtonText: '退出',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  userStore.logout()
  ElMessage.success('已退出登录')
  await router.replace('/login')
}

/** 用户下拉菜单命令分发 */
function handleCommand(command: string): void {
  if (command === 'password') {
    openPasswordDialog()
    return
  }
  if (command === 'logout') {
    void handleLogout()
  }
}

onMounted(() => {
  if (!userStore.isLoggedIn) return
  // 刷新页面后补齐用户信息与项目列表，保证顶部「当前项目」可用
  if (!userStore.userInfo) void userStore.fetchMe().catch(() => undefined)
  if (!projectStore.projects.length) void projectStore.loadProjects().catch(() => undefined)
})
</script>

<template>
  <router-view v-if="isStandalone" />

  <el-container v-else class="app-shell">
    <el-aside :width="isCollapse ? '64px' : '210px'" class="app-aside">
      <div class="app-logo">
        <span class="app-logo__mark">AT</span>
        <span v-show="!isCollapse" class="app-logo__text">auto-test-platform</span>
      </div>
      <el-menu
        :default-active="activeMenu"
        :collapse="isCollapse"
        :collapse-transition="false"
        router
        class="app-menu"
      >
        <el-menu-item v-for="item in menus" :key="item.path" :index="item.path">
          <el-icon><component :is="item.icon" /></el-icon>
          <template #title>{{ item.title }}</template>
        </el-menu-item>
      </el-menu>
    </el-aside>

    <el-container>
      <el-header class="app-header">
        <div class="app-header__left">
          <el-button
            text
            class="app-header__collapse"
            :icon="isCollapse ? Expand : Fold"
            @click="isCollapse = !isCollapse"
          />
          <el-breadcrumb separator="/">
            <el-breadcrumb-item :to="{ path: '/' }">首页</el-breadcrumb-item>
            <el-breadcrumb-item v-if="route.path !== '/'">{{ route.meta.title }}</el-breadcrumb-item>
          </el-breadcrumb>
        </div>

        <div class="app-header__right">
          <el-tag
            v-if="projectStore.currentProject"
            type="success"
            effect="plain"
            size="small"
            class="app-header__project"
          >
            当前项目：{{ projectStore.currentProject.name }}
          </el-tag>
          <el-tag
            v-else
            type="warning"
            effect="plain"
            size="small"
            class="app-header__project app-header__project--empty"
            @click="router.push('/projects')"
          >
            未选择项目 · 前往「项目管理」选择
          </el-tag>

          <el-dropdown @command="handleCommand">
            <span class="app-user">
              <el-icon><User /></el-icon>
              <span class="app-user__name">{{ userStore.userInfo?.username ?? '未登录' }}</span>
              <el-icon><ArrowDown /></el-icon>
            </span>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="password">
                  <el-icon><Lock /></el-icon>
                  修改密码
                </el-dropdown-item>
                <el-dropdown-item command="logout" divided>
                  <el-icon><SwitchButton /></el-icon>
                  退出登录
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </el-header>

      <el-main class="app-main">
        <router-view />
      </el-main>
    </el-container>
  </el-container>

  <el-dialog v-model="passwordVisible" title="修改密码" width="440px" append-to-body>
    <el-form
      ref="passwordFormRef"
      :model="passwordForm"
      :rules="passwordRules"
      label-width="90px"
      @submit.prevent
    >
      <el-form-item label="原密码" prop="old_password">
        <el-input v-model="passwordForm.old_password" type="password" show-password />
      </el-form-item>
      <el-form-item label="新密码" prop="new_password">
        <el-input v-model="passwordForm.new_password" type="password" show-password />
      </el-form-item>
      <el-form-item label="确认密码" prop="confirm_password">
        <el-input
          v-model="passwordForm.confirm_password"
          type="password"
          show-password
          @keyup.enter="submitPassword"
        />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="passwordVisible = false">取消</el-button>
      <el-button type="primary" :loading="passwordSubmitting" @click="submitPassword">
        确定
      </el-button>
    </template>
  </el-dialog>
</template>

<style>
/* 全局基础样式：body / html 不属于 App 组件范围，只能用非 scoped 样式设置 */
html,
body,
#app {
  height: 100%;
  margin: 0;
  padding: 0;
}

body {
  background-color: var(--el-bg-color-page);
  color: var(--el-text-color-primary);
  font-family: 'Helvetica Neue', Helvetica, 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei',
    Arial, sans-serif;
  font-size: 14px;
}

/* 报告中展示 JSON / 堆栈的等宽块 */
.code-block {
  margin: 0;
  padding: 10px 12px;
  max-height: 320px;
  overflow: auto;
  border-radius: 4px;
  background-color: #1f2430;
  color: #e6e6e6;
  font-family: 'JetBrains Mono', Consolas, Monaco, 'Courier New', monospace;
  font-size: 12px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-all;
}
</style>

<style scoped>
.app-shell {
  height: 100vh;
}

.app-aside {
  display: flex;
  flex-direction: column;
  background-color: #ffffff;
  border-right: 1px solid var(--el-border-color-light);
  transition: width 0.2s;
  overflow: hidden;
}

.app-logo {
  display: flex;
  align-items: center;
  gap: 10px;
  height: 60px;
  padding: 0 16px;
  border-bottom: 1px solid var(--el-border-color-lighter);
  white-space: nowrap;
}

.app-logo__mark {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border-radius: 6px;
  background-color: var(--el-color-primary);
  color: #ffffff;
  font-size: 13px;
  font-weight: 600;
  flex-shrink: 0;
}

.app-logo__text {
  font-size: 14px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}

.app-menu {
  flex: 1;
  border-right: none;
  overflow-y: auto;
}

.app-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 60px;
  padding: 0 16px;
  background-color: #ffffff;
  border-bottom: 1px solid var(--el-border-color-light);
}

.app-header__left,
.app-header__right {
  display: flex;
  align-items: center;
  gap: 12px;
}

.app-header__collapse {
  color: var(--el-text-color-regular);
}

.app-header__project {
  font-weight: 400;
}

.app-header__project--empty {
  cursor: pointer;
}

.app-user {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--el-text-color-regular);
  cursor: pointer;
  outline: none;
}

.app-user__name {
  font-size: 14px;
}

.app-main {
  padding: 16px;
  background-color: var(--el-bg-color-page);
  overflow-y: auto;
}
</style>
