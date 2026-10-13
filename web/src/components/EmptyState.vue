<template>
  <div class="empty-state app-card">
    <el-icon :size="42" class="es-icon"><component :is="icon" /></el-icon>
    <p class="es-desc">{{ description }}</p>
    <el-button v-if="actionText" type="primary" @click="$emit('action')">{{ actionText }}</el-button>
  </div>
</template>

<script setup lang="ts">
withDefaults(defineProps<{ description: string; actionText?: string; icon?: string }>(), {
  icon: 'Box',
})
defineEmits<{ action: [] }>()
</script>

<style scoped>
.empty-state {
  padding: 56px 24px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 14px;
  text-align: center;
}
.es-icon { color: var(--text-muted); }
.es-desc { margin: 0; color: var(--text-secondary); font-size: 14px; }
</style>
