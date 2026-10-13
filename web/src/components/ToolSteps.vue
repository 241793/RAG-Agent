<template>
  <div class="steps">
    <el-collapse>
      <el-collapse-item v-for="(s, i) in steps" :key="i">
        <template #title>
          <span class="step-title">
            <el-icon><Tools /></el-icon>
            <span>调用 {{ s.call.name }}</span>
            <el-tag v-if="!s.result" size="small" type="info">执行中</el-tag>
            <el-tag v-else-if="s.result.is_error" size="small" type="danger">失败</el-tag>
            <el-tag v-else size="small" type="success">完成</el-tag>
          </span>
        </template>
        <div class="step-body">
          <div class="step-label">参数：</div>
          <pre class="step-pre">{{ s.call.arguments }}</pre>
          <template v-if="s.result">
            <div class="step-label">结果：</div>
            <pre class="step-pre step-result">{{ s.result.content }}</pre>
          </template>
        </div>
      </el-collapse-item>
    </el-collapse>
  </div>
</template>

<script setup lang="ts">
interface Step {
  call: { id: string; name: string; arguments: string }
  result?: { id: string; name: string; content: string; is_error: boolean }
}
defineProps<{ steps: Step[] }>()
</script>

<style scoped>
.steps { margin-bottom: 8px; }
.step-title { display: inline-flex; align-items: center; gap: 8px; font-size: 13px; }
.step-title .el-icon { color: var(--text-secondary); }
.step-body { font-size: 12px; }
.step-label { color: var(--text-secondary); margin: 4px 0 2px; }
.step-pre {
  margin: 0; white-space: pre-wrap; word-break: break-word;
  background: var(--bg-subtle); padding: 8px 10px; border-radius: 6px;
  font-family: 'SFMono-Regular', Consolas, monospace;
}
.step-result { max-height: 200px; overflow: auto; }
</style>
