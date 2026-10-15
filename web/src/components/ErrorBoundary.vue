<template>
  <div v-if="err" class="eb-wrap app-card">
    <el-result status="error" title="页面出错了" :sub-title="errMsg">
      <template #extra>
        <el-button type="primary" @click="reset">重试</el-button>
        <el-button @click="goHome">回工作台</el-button>
      </template>
    </el-result>
  </div>
  <slot v-else />
</template>

<script setup lang="ts">
/**
 * 页面级错误边界：捕获子组件（含路由页）渲染/生命周期异常，
 * 显示友好结果页并可重试，避免整页白屏。切换路由时自动复位。
 */
import { onErrorCaptured, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

const route = useRoute()
const router = useRouter()
const err = ref(false)
const errMsg = ref('')

onErrorCaptured((e) => {
  err.value = true
  errMsg.value = (e instanceof Error ? e.message : String(e)).slice(0, 200)
  console.error('[ErrorBoundary]', e)
  return false // 阻止继续冒泡
})

// 切换路由时复位，重新渲染新页面
watch(() => route.fullPath, () => { err.value = false; errMsg.value = '' })

function reset() { err.value = false; errMsg.value = '' }
function goHome() { reset(); router.push('/dashboard') }
</script>

<style scoped>
.eb-wrap { padding: 40px 20px; display: flex; justify-content: center; }
</style>
