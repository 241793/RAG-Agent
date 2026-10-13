<template>
  <PageContainer title="系统设置" subtitle="按分组维护平台参数；带「需重启」标记的字段保存后需重启服务才能生效">
    <template #extra>
      <el-button :disabled="!dirtyCount" type="primary" :icon="Check" @click="save">保存（{{ dirtyCount }}）</el-button>
      <el-button :icon="RefreshRight" @click="restartService">重启服务</el-button>
    </template>

    <el-skeleton v-if="loading" :rows="6" animated />

    <div v-else-if="!fields.length" class="app-card panel">
      <el-empty description="暂无可用设置项" />
    </div>

    <div v-else class="app-card panel">
      <el-tabs v-model="activeGroup">
        <el-tab-pane v-for="g in groups" :key="g.key" :name="g.key">
          <template #label>
            <span>{{ g.label }}</span>
            <el-badge v-if="groupDirty[g.key]" :value="groupDirty[g.key]" class="grp-badge" />
          </template>

          <el-form label-position="top" class="setting-form">
            <el-form-item v-for="f in fieldsByGroup[g.key] || []" :key="f.key">
              <template #label>
                <span class="lbl">{{ f.label || f.key }}</span>
                <el-tag v-if="f.restart" size="small" type="warning" style="margin-left: 6px">需重启</el-tag>
                <el-tooltip v-if="f.help" :content="f.help" placement="top">
                  <el-icon class="help"><QuestionFilled /></el-icon>
                </el-tooltip>
              </template>

              <el-switch v-if="f.kind === 'bool'" v-model="model[f.key]" />

              <el-input-number
                v-else-if="f.kind === 'int' || f.kind === 'float'"
                v-model="model[f.key]"
                :step="f.kind === 'float' ? 0.1 : 1"
                :controls-position="'right'"
              />

              <el-select
                v-else-if="f.kind === 'csv'"
                v-model="model[f.key]"
                multiple
                filterable
                allow-create
                default-first-option
                style="width: 100%"
                placeholder="输入后回车添加"
              />

              <el-input
                v-else-if="f.kind === 'secret'"
                v-model="model[f.key]"
                type="password"
                show-password
                :placeholder="f.is_set ? '已设置，留空保持不变' : '未设置'"
              />

              <el-input
                v-else-if="f.kind === 'json'"
                v-model="model[f.key]"
                type="textarea"
                :rows="4"
                class="mono"
              />

              <el-input v-else v-model="model[f.key]" />

              <div v-if="f.help" class="extra">{{ f.help }}</div>
              <div class="extra key-hint">{{ f.key }}</div>
            </el-form-item>
          </el-form>
        </el-tab-pane>
      </el-tabs>
    </div>
  </PageContainer>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Check, RefreshRight, QuestionFilled } from '@element-plus/icons-vue'
import PageContainer from '@/components/PageContainer.vue'
import { settingsApi, type SettingField } from '@/api'
import { errMsg } from '@/api/http'

const loading = ref(true)
const groups = ref<{ key: string; label: string }[]>([])
const fields = ref<SettingField[]>([])
const activeGroup = ref('')
const model = reactive<Record<string, any>>({})
const originals = reactive<Record<string, any>>({})

const fieldsByGroup = computed(() => {
  const m: Record<string, SettingField[]> = {}
  for (const f of fields.value) (m[f.group] = m[f.group] || []).push(f)
  return m
})

function toEditable(f: SettingField): any {
  if (f.kind === 'csv') {
    if (Array.isArray(f.value)) return [...f.value]
    if (typeof f.value === 'string') return f.value.split(',').map((s) => s.trim()).filter(Boolean)
    return []
  }
  if (f.kind === 'secret') return ''
  if (f.kind === 'int' || f.kind === 'float') {
    const n = Number(f.value)
    return Number.isFinite(n) ? n : 0
  }
  if (f.kind === 'json') {
    try { return typeof f.value === 'string' ? f.value : JSON.stringify(f.value ?? {}, null, 2) } catch { return '' }
  }
  return f.value ?? ''
}

async function load() {
  loading.value = true
  try {
    const r = await settingsApi.get()
    groups.value = r.groups || []
    fields.value = r.fields || []
    Object.keys(model).forEach((k) => delete model[k])
    Object.keys(originals).forEach((k) => delete originals[k])
    for (const f of fields.value) {
      const v = toEditable(f)
      model[f.key] = v
      originals[f.key] = JSON.stringify(v)
    }
    if (!activeGroup.value || !groups.value.some((g) => g.key === activeGroup.value)) {
      activeGroup.value = groups.value[0]?.key || ''
    }
  } catch (e) { ElMessage.error(errMsg(e)) } finally { loading.value = false }
}

const dirtyKeys = computed(() => fields.value.filter((f) => JSON.stringify(model[f.key]) !== originals[f.key]).map((f) => f.key))
const dirtyCount = computed(() => dirtyKeys.value.length)
const groupDirty = computed(() => {
  const m: Record<string, number> = {}
  for (const f of fields.value) if (JSON.stringify(model[f.key]) !== originals[f.key]) m[f.group] = (m[f.group] || 0) + 1
  return m
})

async function save() {
  if (!dirtyCount.value) { ElMessage.info('没有需要保存的改动'); return }
  const updates: Record<string, any> = {}
  let hasRestart = false
  for (const f of fields.value) {
    if (JSON.stringify(model[f.key]) === originals[f.key]) continue
    let v = model[f.key]
    if (f.kind === 'csv' && Array.isArray(v)) v = v.join(',')
    if (f.kind === 'secret' && !v) continue // 留空表示不变
    if (f.kind === 'int') v = Math.trunc(Number(v) || 0)
    if (f.kind === 'float') v = Number(v) || 0
    updates[f.key] = v
    if (f.restart) hasRestart = true
  }
  if (!Object.keys(updates).length) { ElMessage.info('没有需要保存的改动'); return }
  try {
    const r = await settingsApi.update(updates)
    ElMessage.success(r.message || '已保存')
    if (r.restart_required) await promptRestart()
    else if (hasRestart) ElMessage.info('部分字段需重启服务后生效')
    load()
  } catch (e) { ElMessage.error(errMsg(e)) }
}

async function promptRestart() {
  try {
    await ElMessageBox.confirm('设置已保存，需重启服务才能完全生效。是否立即重启？', '需要重启', {
      confirmButtonText: '立即重启', cancelButtonText: '稍后', type: 'warning',
    })
  } catch { return }
  await doRestart()
}
async function restartService() {
  try {
    await ElMessageBox.confirm('确定重启服务？重启期间可能短暂不可用。', '重启服务', {
      confirmButtonText: '重启', cancelButtonText: '取消', type: 'warning',
    })
  } catch { return }
  await doRestart()
}
async function doRestart() {
  try { const r = await settingsApi.restart(); ElMessage.success(r.message || '重启指令已下发') } catch (e) { ElMessage.error(errMsg(e)) }
}

onMounted(load)
</script>

<style scoped>
.panel { padding: 18px 20px; }
.setting-form { max-width: 640px; }
.lbl { color: var(--text-title); font-weight: 500; }
.help { color: var(--text-muted); cursor: help; margin-left: 6px; }
.extra { font-size: 12px; color: var(--text-muted); line-height: 1.5; }
.key-hint { font-family: monospace; margin-top: 2px; }
.mono :deep(textarea) { font-family: monospace; font-size: 12px; }
.grp-badge { margin-left: 6px; transform: translateY(-2px); }
</style>
