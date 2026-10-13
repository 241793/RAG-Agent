<template>
  <PageContainer title="使用文档" subtitle="各界面功能、使用方法，以及与 AI 的配合方式。左侧目录可跳转，支持搜索。">
    <div class="docs-wrap">
      <!-- 目录 -->
      <aside class="docs-toc app-card">
        <el-input v-model="q" placeholder="搜索功能 / 关键词" clearable :prefix-icon="Search" size="small" class="toc-search" />
        <el-scrollbar class="toc-scroll">
          <div
            v-for="s in filtered"
            :key="s.id"
            class="toc-item"
            :class="{ active: activeId === s.id }"
            @click="jump(s.id)"
          >
            <el-icon class="toc-ico"><component :is="s.icon" /></el-icon>
            <span class="toc-label">{{ s.title }}</span>
          </div>
          <el-empty v-if="!filtered.length" description="无匹配" :image-size="50" />
        </el-scrollbar>
      </aside>

      <!-- 正文 -->
      <section class="docs-body">
        <el-scrollbar class="body-scroll" ref="bodyRef">
          <div v-if="!filtered.length" class="docs-empty">
            <el-empty description="没有匹配「{{ q }}」的内容，换个关键词试试" :image-size="90" />
          </div>
          <div v-for="s in filtered" :key="s.id" :id="`doc-${s.id}`" class="doc-section app-card">
            <div class="ds-head">
              <span class="ds-icon"><el-icon :size="20"><component :is="s.icon" /></el-icon></span>
              <h2 class="ds-title">{{ s.title }}</h2>
            </div>
            <p class="ds-summary">{{ s.summary }}</p>
            <div class="ds-items">
              <div v-for="(it, i) in s.items" :key="i" class="doc-item">
                <div class="di-name">{{ it.name }}</div>
                <div class="di-desc">{{ it.desc }}</div>
                <div v-if="it.ai" class="di-ai">
                  <el-icon class="di-ai-ico"><MagicStick /></el-icon>
                  <span><b>与 AI 的配合：</b>{{ it.ai }}</span>
                </div>
              </div>
            </div>
          </div>

          <div class="docs-foot">
            <el-icon><InfoFilled /></el-icon>
            以上为各界面功能说明。若某项看不到，通常是没有对应权限——请联系管理员在「组织权限」里授予。
          </div>
        </el-scrollbar>
      </section>
    </div>
  </PageContainer>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { Search, MagicStick, InfoFilled } from '@element-plus/icons-vue'
import PageContainer from '@/components/PageContainer.vue'
import { DOCS } from '@/config/docs'

const q = ref('')
const activeId = ref(DOCS[0]?.id || '')
const bodyRef = ref<any>(null)

const filtered = computed(() => {
  const kw = q.value.trim().toLowerCase()
  if (!kw) return DOCS
  return DOCS.filter((s) => {
    const hay = `${s.title} ${s.summary} ${s.items.map((i) => `${i.name} ${i.desc} ${i.ai || ''}`).join(' ')}`.toLowerCase()
    return hay.includes(kw)
  })
})

function jump(id: string) {
  activeId.value = id
  const el = document.getElementById(`doc-${id}`)
  if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

// 滚动时高亮当前节
function onScroll() {
  const wrap = bodyRef.value?.wrapRef as HTMLElement | undefined
  if (!wrap) return
  const top = wrap.scrollTop + 80
  let cur = filtered.value[0]?.id
  for (const s of filtered.value) {
    const el = document.getElementById(`doc-${s.id}`)
    if (el && el.offsetTop <= top) cur = s.id
  }
  if (cur) activeId.value = cur
}
onMounted(() => {
  bodyRef.value?.wrapRef?.addEventListener('scroll', onScroll)
})
onUnmounted(() => {
  bodyRef.value?.wrapRef?.removeEventListener('scroll', onScroll)
})
</script>

<style scoped>
.docs-wrap {
  display: grid; grid-template-columns: 250px 1fr; gap: 16px;
  height: calc(100vh - var(--header-h) - 48px); min-height: 520px; overflow: hidden;
}

.docs-toc { display: flex; flex-direction: column; overflow: hidden; padding: 12px; min-height: 0; }
.toc-search { margin-bottom: 10px; }
.toc-scroll { flex: 1; min-height: 0; }
.toc-item { display: flex; align-items: center; gap: 8px; padding: 8px 10px; border-radius: 8px; cursor: pointer; font-size: 13px; color: var(--text-body); }
.toc-item:hover { background: var(--bg-subtle); }
.toc-item.active { background: var(--color-primary-subtle); color: var(--brand-700); font-weight: 600; }
.toc-ico { color: var(--text-muted); font-size: 15px; }
.toc-item.active .toc-ico { color: var(--color-primary); }
.toc-label { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.docs-body { min-width: 0; min-height: 0; overflow: hidden; }
.body-scroll { height: 100%; }
.doc-section { padding: 20px 24px; margin-bottom: 16px; scroll-margin-top: 12px; }
.ds-head { display: flex; align-items: center; gap: 10px; }
.ds-icon { width: 38px; height: 38px; border-radius: 10px; background: var(--color-primary-subtle); color: var(--color-primary); display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
.ds-title { font-size: 18px; font-weight: 600; color: var(--text-title); margin: 0; letter-spacing: -0.01em; }
.ds-summary { font-size: 13.5px; color: var(--text-secondary); line-height: 1.7; margin: 12px 0 16px; }
.ds-items { display: flex; flex-direction: column; gap: 12px; }
.doc-item { border-left: 3px solid var(--border); padding: 2px 0 2px 12px; }
.di-name { font-size: 14px; font-weight: 600; color: var(--text-title); }
.di-desc { font-size: 13px; color: var(--text-body); line-height: 1.7; margin-top: 3px; }
.di-ai { display: flex; gap: 6px; margin-top: 6px; font-size: 12.5px; color: var(--brand-700); background: var(--color-primary-subtle); border: 1px solid var(--color-primary-border); border-radius: 8px; padding: 7px 10px; line-height: 1.6; }
.di-ai-ico { color: var(--color-primary); flex-shrink: 0; margin-top: 2px; }
.docs-foot { display: flex; align-items: center; gap: 8px; font-size: 12.5px; color: var(--text-muted); padding: 8px 4px 24px; }
.docs-empty { padding: 40px 0; }

@media (max-width: 900px) {
  .docs-wrap { grid-template-columns: 1fr; }
  .docs-toc { display: none; }
}
</style>
