<template>
  <div class="placeholder">
    <div class="ph-icon"><el-icon :size="30"><Tools /></el-icon></div>
    <h2 class="ph-title">{{ title }}</h2>
    <p class="ph-desc">{{ desc }}</p>
    <div class="ph-tags">
      <span class="badge-pill blue">功能占位</span>
      <span class="badge-pill gray">Vue3 重写进行中</span>
    </div>
    <p class="ph-note">
      该模块的完整业务逻辑可沿用现有后端接口（零改动）继续实现；
      当前示例聚焦「浅色商业级设计 + 主框架 + 核心页面」。
    </p>
    <el-button type="primary" plain @click="$router.push('/dashboard')">返回工作台</el-button>
  </div>
</template>

<script setup lang="ts">
defineProps<{ title: string; desc?: string }>()
</script>

<style scoped>
.placeholder {
  max-width: 560px;
  margin: 72px auto;
  text-align: center;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
}
.ph-icon {
  width: 64px; height: 64px; border-radius: 18px;
  background: var(--color-primary-subtle); color: var(--color-primary);
  display: flex; align-items: center; justify-content: center;
  margin-bottom: 4px;
}
.ph-title { margin: 0; font-size: 20px; font-weight: 600; color: var(--text-title); }
.ph-desc { margin: 0; color: var(--text-secondary); font-size: 14px; }
.ph-tags { display: flex; gap: 8px; margin: 4px 0 8px; }
.ph-note { color: var(--text-muted); font-size: 13px; line-height: 1.6; margin: 0 0 8px; }
</style>
