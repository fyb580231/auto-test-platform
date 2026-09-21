/**
 * 应用入口：装配 Pinia、Vue Router、Element Plus（中文语言包）并挂载根组件。
 */
import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import zhCn from 'element-plus/es/locale/lang/zh-cn'

import 'element-plus/dist/index.css'

import App from '@/App.vue'
import router from '@/router'

const app = createApp(App)

// Pinia 必须先于 router 安装：路由守卫中会使用 store
app.use(createPinia())
app.use(router)
app.use(ElementPlus, { locale: zhCn, size: 'default' })

app.mount('#app')
