<!--
  ProjectList.vue —— 项目管理。

  职责：
  1. 项目列表（名称、描述、用例数、用例集数、环境数、创建时间）；
  2. 新建 / 编辑（对话框）/ 删除（二次确认）；
  3. 「进入项目」把项目设为当前项目（写入 Pinia + localStorage）并跳转到用例管理。
-->
<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from 'element-plus'
import { Delete, Edit, Plus, Refresh, Search, Select } from '@element-plus/icons-vue'

import { createProject, deleteProject, updateProject } from '@/api/project'
import { useProjectStore } from '@/stores/project'
import type { Project } from '@/types'
import { formatDateTime } from '@/utils/format'

const router = useRouter()
const projectStore = useProjectStore()

const keyword = ref('')

/* -------------------------------- 列表加载 ------------------------------- */
async function loadProjects(): Promise<void> {
  try {
    await projectStore.loadProjects(keyword.value.trim() || undefined)
  } catch {
    // 错误提示已由 axios 拦截器统一处理
  }
}

/** 重置筛选条件并重新查询 */
async function handleReset(): Promise<void> {
  keyword.value = ''
  await loadProjects()
}

/* ------------------------------ 新建 / 编辑 ------------------------------ */
const dialogVisible = ref(false)
const dialogSubmitting = ref(false)
const editingId = ref<number | null>(null)
const formRef = ref<FormInstance>()
const form = reactive({
  name: '',
  description: '',
})

const dialogTitle = ref('新建项目')

const rules: FormRules<typeof form> = {
  name: [{ required: true, message: '请输入项目名称', trigger: 'blur' }],
}

/** 打开新建对话框 */
function openCreate(): void {
  editingId.value = null
  dialogTitle.value = '新建项目'
  form.name = ''
  form.description = ''
  dialogVisible.value = true
  void formRef.value?.clearValidate()
}

/** 打开编辑对话框 */
function openEdit(project: Project): void {
  editingId.value = project.id
  dialogTitle.value = '编辑项目'
  form.name = project.name
  form.description = project.description ?? ''
  dialogVisible.value = true
  void formRef.value?.clearValidate()
}

/** 提交新建 / 编辑 */
async function handleSubmit(): Promise<void> {
  if (!formRef.value) return
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return

  dialogSubmitting.value = true
  try {
    const payload = { name: form.name.trim(), description: form.description.trim() || null }
    if (editingId.value) {
      await updateProject(editingId.value, payload)
      ElMessage.success('项目已更新')
    } else {
      await createProject(payload)
      ElMessage.success('项目已创建')
    }
    dialogVisible.value = false
    await loadProjects()
  } catch {
    // 错误提示已由 axios 拦截器统一处理
  } finally {
    dialogSubmitting.value = false
  }
}

/* --------------------------------- 删除 --------------------------------- */
async function handleDelete(project: Project): Promise<void> {
  try {
    await ElMessageBox.confirm(
      `删除后该项目下的 ${project.case_count} 条用例、${project.suite_count} 个用例集与 ${project.environment_count} 个环境都会一并删除，且无法恢复。是否继续？`,
      `删除项目「${project.name}」`,
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消', confirmButtonClass: 'el-button--danger' },
    )
  } catch {
    return
  }

  try {
    const result = await deleteProject(project.id)
    ElMessage.success(result.message || '项目已删除')
    if (projectStore.currentProjectId === project.id) {
      projectStore.setCurrentProject(null)
    }
    await loadProjects()
  } catch {
    // 错误提示已由 axios 拦截器统一处理
  }
}

/* ------------------------------- 进入项目 ------------------------------- */
function handleEnter(project: Project): void {
  projectStore.setCurrentProject(project.id)
  ElMessage.success(`已切换到项目「${project.name}」`)
  void router.push('/cases')
}

onMounted(() => {
  void loadProjects()
})
</script>

<template>
  <div class="project-list">
    <el-card shadow="never" class="project-list__toolbar">
      <div class="project-list__filters">
        <el-input
          v-model="keyword"
          placeholder="搜索项目名称"
          :prefix-icon="Search"
          clearable
          class="project-list__search"
          @keyup.enter="loadProjects"
          @clear="loadProjects"
        />
        <el-button type="primary" :icon="Search" @click="loadProjects">查询</el-button>
        <el-button :icon="Refresh" @click="handleReset">重置</el-button>
      </div>
      <el-button type="primary" :icon="Plus" @click="openCreate">新建项目</el-button>
    </el-card>

    <el-card shadow="never">
      <el-table v-loading="projectStore.loading" :data="projectStore.projects" row-key="id">
        <el-table-column label="项目名称" min-width="200">
          <template #default="{ row }">
            <div class="project-cell">
              <span class="project-cell__name">{{ row.name }}</span>
              <el-tag v-if="projectStore.currentProjectId === row.id" size="small" type="success" effect="plain">
                当前项目
              </el-tag>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="description" label="描述" min-width="240" show-overflow-tooltip>
          <template #default="{ row }">{{ row.description || '-' }}</template>
        </el-table-column>
        <el-table-column prop="case_count" label="用例数" width="90" align="center" />
        <el-table-column prop="suite_count" label="用例集数" width="100" align="center" />
        <el-table-column prop="environment_count" label="环境数" width="90" align="center" />
        <el-table-column label="创建时间" width="170">
          <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="230" fixed="right">
          <template #default="{ row }">
            <!-- el-table 插槽的 row 是宽松记录类型，这里断言成业务类型后传给处理函数 -->
            <el-button text type="primary" :icon="Select" @click="handleEnter(row as Project)">
              进入
            </el-button>
            <el-button text :icon="Edit" @click="openEdit(row as Project)">编辑</el-button>
            <el-button text type="danger" :icon="Delete" @click="handleDelete(row as Project)">
              删除
            </el-button>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="暂无项目，点击右上角「新建项目」开始" :image-size="90" />
        </template>
      </el-table>
    </el-card>

    <el-dialog v-model="dialogVisible" :title="dialogTitle" width="480px">
      <el-form ref="formRef" :model="form" :rules="rules" label-width="90px" @submit.prevent>
        <el-form-item label="项目名称" prop="name">
          <el-input v-model="form.name" placeholder="例如：电商平台接口测试" maxlength="128" show-word-limit />
        </el-form-item>
        <el-form-item label="描述">
          <el-input
            v-model="form.description"
            type="textarea"
            :rows="3"
            resize="none"
            placeholder="项目背景、被测系统说明等"
            maxlength="2000"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="dialogSubmitting" @click="handleSubmit">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.project-list__toolbar {
  margin-bottom: 16px;
}

.project-list__toolbar :deep(.el-card__body) {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px;
}

.project-list__filters {
  display: flex;
  align-items: center;
  gap: 8px;
}

.project-list__search {
  width: 260px;
}

.project-cell {
  display: flex;
  align-items: center;
  gap: 8px;
}

.project-cell__name {
  font-weight: 600;
}
</style>
