<template>
  <el-drawer :model-value="modelValue" title="群机器人" size="420px" @update:model-value="(v: boolean) => $emit('update:modelValue', v)">
    <p class="hint">把智能体拉进群作为机器人。群里 <b>@机器人名</b> 才会响应，回复会自动 @提问者。</p>
    <div class="add-row">
      <el-select v-model="pick" filterable placeholder="选择智能体" style="flex: 1">
        <el-option v-for="a in agents" :key="a.id" :value="a.id" :label="a.name" />
      </el-select>
      <el-button type="primary" @click="add">添加</el-button>
    </div>
    <el-empty v-if="!bots.length" description="暂无机器人" :image-size="70" />
    <div v-for="b in bots" :key="b.agent_id" class="bot-row">
      <el-avatar :size="28" style="background: #7c3aed"><el-icon><MagicStick /></el-icon></el-avatar>
      <span class="bot-name">{{ b.name }}</span>
      <el-button size="small" link type="danger" @click="remove(b)">移出</el-button>
    </div>
  </el-drawer>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { MagicStick } from '@element-plus/icons-vue'
import { chatRoomApi, type RoomDetail } from '@/api'
import { errMsg } from '@/api/http'

const props = defineProps<{ modelValue: boolean; detail: RoomDetail | null; agents: any[] }>()
const emit = defineEmits<{ 'update:modelValue': [v: boolean]; changed: [] }>()

const pick = ref<number>()
const bots = computed(() => props.detail?.bots || [])

async function add() {
  if (!pick.value || !props.detail) return
  try {
    await chatRoomApi.addBot(props.detail.id, pick.value)
    pick.value = undefined
    ElMessage.success('已添加')
    emit('changed')
  } catch (e) { ElMessage.error(errMsg(e)) }
}
async function remove(b: any) {
  if (!props.detail) return
  try {
    await chatRoomApi.removeBot(props.detail.id, b.agent_id)
    emit('changed')
  } catch (e) { ElMessage.error(errMsg(e)) }
}
</script>

<style scoped>
.hint { font-size: 12px; color: var(--text-secondary); line-height: 1.6; margin: 0 0 12px; }
.add-row { display: flex; gap: 8px; margin-bottom: 12px; }
.bot-row { display: flex; align-items: center; gap: 10px; padding: 8px 4px; border-bottom: 1px solid var(--border-subtle); }
.bot-name { flex: 1; font-size: 13px; color: var(--text-title); }
</style>
