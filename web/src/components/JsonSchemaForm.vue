<template>
  <div class="jsf">
    <div v-if="!keys.length" class="jsf-empty">该 Schema 无参数定义</div>
    <div v-for="key in keys" :key="key" class="jsf-item">
      <label class="jsf-label" :class="{ req: required.has(key) }">{{ props_[key]?.title || key }}</label>
      <div class="jsf-control">
        <!-- enum -->
        <el-select
          v-if="props_[key]?.enum"
          :model-value="model[key]"
          :disabled="disabled"
          :placeholder="props_[key]?.description || ''"
          style="width: 100%"
          @update:model-value="(v: any) => set(key, v)"
        >
          <el-option v-for="e in props_[key].enum" :key="String(e)" :value="e" :label="String(e)" />
        </el-select>
        <!-- boolean -->
        <el-switch
          v-else-if="typeOf(key) === 'boolean'"
          :model-value="!!model[key]"
          :disabled="disabled"
          @update:model-value="(v: any) => set(key, v)"
        />
        <!-- number -->
        <el-input-number
          v-else-if="typeOf(key) === 'integer' || typeOf(key) === 'number'"
          :model-value="model[key]"
          :disabled="disabled"
          style="width: 100%"
          @update:model-value="(v: any) => set(key, v)"
        />
        <!-- array -->
        <el-select
          v-else-if="typeOf(key) === 'array' && props_[key]?.items?.enum"
          :model-value="model[key] || []"
          multiple
          :disabled="disabled"
          :placeholder="props_[key]?.description || ''"
          style="width: 100%"
          @update:model-value="(v: any) => set(key, v)"
        >
          <el-option v-for="e in props_[key].items.enum" :key="String(e)" :value="e" :label="String(e)" />
        </el-select>
        <el-select
          v-else-if="typeOf(key) === 'array'"
          :model-value="model[key] || []"
          multiple
          filterable
          allow-create
          default-first-option
          :disabled="disabled"
          :placeholder="props_[key]?.description || '回车添加'"
          style="width: 100%"
          @update:model-value="(v: any) => set(key, v)"
        />
        <!-- textarea -->
        <el-input
          v-else-if="isTextarea(key)"
          :model-value="model[key]"
          type="textarea"
          :rows="3"
          :disabled="disabled"
          :placeholder="props_[key]?.description || ''"
          @update:model-value="(v: any) => set(key, v)"
        />
        <!-- string -->
        <el-input
          v-else
          :model-value="model[key]"
          :disabled="disabled"
          :placeholder="props_[key]?.description || ''"
          @update:model-value="(v: any) => set(key, v)"
        />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

interface JsonSchema {
  type?: string
  properties?: Record<any, any>
  required?: string[]
  items?: any
  title?: string
  description?: string
  enum?: any[]
  format?: string
}

const props = withDefaults(
  defineProps<{ schema?: JsonSchema | null; modelValue: Record<string, any>; disabled?: boolean }>(),
  { disabled: false },
)
const emit = defineEmits<{ 'update:modelValue': [v: Record<string, any>] }>()

const props_ = computed<Record<string, any>>(() => props.schema?.properties || {})
const keys = computed(() => Object.keys(props_.value))
const required = computed(() => new Set(props.schema?.required || []))
const model = computed(() => props.modelValue || {})

function typeOf(key: string) {
  const p = props_.value[key] || {}
  return p.type || (p.enum ? 'string' : 'string')
}
function isTextarea(key: string) {
  const p = props_.value[key] || {}
  return p.format === 'textarea' || String(p.title || '').includes('描述') || String(p.description || '').includes('多行')
}
function set(key: string, v: any) {
  emit('update:modelValue', { ...model.value, [key]: v })
}
</script>

<style scoped>
.jsf-empty { color: var(--text-muted); font-size: 12px; }
.jsf-item { margin-bottom: 14px; }
.jsf-label { display: block; font-size: 13px; color: var(--text-body); margin-bottom: 6px; }
.jsf-label.req::after { content: ' *'; color: var(--error); }
</style>
