<!--
  Login.vue —— 登录页。

  职责：
  1. 账号密码登录（支持回车提交），登录成功后跳转到 `redirect` 或首页；
  2. 展示演示账号提示，保证评审者能直接登录体验。
-->
<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { Lock, User } from '@element-plus/icons-vue'

import { useUserStore } from '@/stores/user'

const router = useRouter()
const route = useRoute()
const userStore = useUserStore()

const formRef = ref<FormInstance>()
const submitting = ref(false)

const form = reactive({
  username: '',
  password: '',
})

const rules: FormRules<typeof form> = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}

/** 提交登录 */
async function handleLogin(): Promise<void> {
  if (!formRef.value) return
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return

  submitting.value = true
  try {
    await userStore.login({ username: form.username.trim(), password: form.password })
    ElMessage.success('登录成功')
    const redirect = typeof route.query.redirect === 'string' ? route.query.redirect : '/'
    await router.replace(redirect)
  } catch {
    // 失败提示已由 axios 响应拦截器统一弹出
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div class="login-page">
    <el-card class="login-card" shadow="never">
      <div class="login-card__head">
        <h1 class="login-card__title">auto-test-platform</h1>
        <p class="login-card__subtitle">接口测试 · UI 测试 · AI 辅助 一体化测试平台</p>
      </div>

      <el-form
        ref="formRef"
        :model="form"
        :rules="rules"
        label-position="top"
        size="large"
        @submit.prevent="handleLogin"
      >
        <el-form-item label="用户名" prop="username">
          <el-input v-model="form.username" placeholder="请输入用户名" :prefix-icon="User" clearable />
        </el-form-item>
        <el-form-item label="密码" prop="password">
          <el-input
            v-model="form.password"
            type="password"
            placeholder="请输入密码"
            :prefix-icon="Lock"
            show-password
            @keyup.enter="handleLogin"
          />
        </el-form-item>
        <el-form-item>
          <el-button
            type="primary"
            class="login-card__submit"
            :loading="submitting"
            native-type="submit"
          >
            登录
          </el-button>
        </el-form-item>
      </el-form>

      <p class="login-card__hint">演示账号：admin / admin123</p>
    </el-card>
  </div>
</template>

<style scoped>
.login-page {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100vh;
  background-color: var(--el-bg-color-page);
}

.login-card {
  width: 400px;
  padding: 8px 12px;
  border-radius: 8px;
  border-color: var(--el-border-color-light);
}

.login-card__head {
  margin-bottom: 20px;
  text-align: center;
}

.login-card__title {
  margin: 0 0 8px;
  font-size: 22px;
  font-weight: 600;
  letter-spacing: 0.3px;
  color: var(--el-text-color-primary);
}

.login-card__subtitle {
  margin: 0;
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.login-card__submit {
  width: 100%;
}

.login-card__hint {
  margin: 4px 0 0;
  padding-top: 12px;
  border-top: 1px solid var(--el-border-color-lighter);
  text-align: center;
  font-size: 12px;
  color: var(--el-text-color-placeholder);
}
</style>
