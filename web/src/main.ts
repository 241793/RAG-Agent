import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus, { ElMessage } from 'element-plus'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import * as ElIcons from '@element-plus/icons-vue'
import 'element-plus/dist/index.css'
import './styles/index.css'
import App from './App.vue'
import router from './router'

const app = createApp(App)
app.use(createPinia())
app.use(router)
app.use(ElementPlus, { locale: zhCn })
// 全局注册 Element Plus 图标，模板里可直接 <el-icon><Search /></el-icon>
for (const [key, comp] of Object.entries(ElIcons)) {
  app.component(key, comp as any)
}

// 全局错误边界：组件渲染/生命周期里未捕获的异常不至于白屏，统一提示并记录。
app.config.errorHandler = (err, _instance, info) => {
  console.error('[app error]', info, err)
  const msg = err instanceof Error ? err.message : String(err)
  ElMessage.error(`页面出现异常（${info}）：${msg.slice(0, 120)}`)
}

app.mount('#app')
