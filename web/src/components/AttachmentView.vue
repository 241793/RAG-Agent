<template>
  <!-- 图片：内嵌 -->
  <el-image
    v-if="kind === 'image' && url"
    :src="absUrl(url)"
    fit="cover"
    :preview-src-list="[absUrl(url)]"
    class="att-image"
    style="width: 180px; height: 120px"
  />

  <!-- 音视频：内嵌播放器 -->
  <template v-else-if="kind === 'video' && url">
    <audio v-if="isAudio" controls :src="absUrl(url)" class="att-audio" />
    <video v-else controls :src="absUrl(url)" class="att-video" />
  </template>

  <!-- PDF：iframe 内嵌 -->
  <div v-else-if="kind === 'pdf' && url" class="att-pdf">
    <iframe :src="absUrl(url)" class="att-pdf-frame" />
    <el-button size="small" link @click="download"><el-icon><Download /></el-icon>下载 PDF</el-button>
  </div>

  <!-- HTML：预览弹框 + 下载 -->
  <div v-else-if="isHtml" class="att-row">
    <el-tag type="primary" class="att-tag" @click="openHtml">
      <el-icon><Document /></el-icon>{{ att.name }}
    </el-tag>
    <el-button size="small" link @click="openHtml">预览</el-button>
    <el-button size="small" link @click="download"><el-icon><Download /></el-icon>下载</el-button>
    <el-dialog
      v-model="htmlOpen"
      :title="att.name"
      width="min(1000px, 92vw)"
      class="att-html-dialog"
      destroy-on-close
      append-to-body
    >
      <iframe
        v-if="htmlUrl"
        :src="htmlUrl"
        :title="att.name"
        sandbox="allow-scripts allow-same-origin"
        class="att-html-frame"
      />
    </el-dialog>
  </div>

  <!-- 文本：抽屉预览 + 下载 -->
  <div v-else-if="kind === 'text'" class="att-row">
    <el-tag class="att-tag" @click="openText">
      <el-icon><Document /></el-icon>{{ att.name }}
    </el-tag>
    <el-button size="small" link @click="download"><el-icon><Download /></el-icon>下载</el-button>
    <el-drawer v-model="textOpen" :title="att.name" size="640px" append-to-body>
      <pre class="att-text">{{ text }}</pre>
    </el-drawer>
  </div>

  <!-- 其它（Office 等）：文件名 + 下载 -->
  <div v-else class="att-row">
    <el-tag class="att-tag" :type="artifact ? 'info' : undefined">
      <el-icon><Paperclip /></el-icon>{{ att.name }}{{ sizeText }}
    </el-tag>
    <el-button size="small" link @click="download"><el-icon><Download /></el-icon>下载</el-button>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { absUrl, fileExt, fmtSize, getArtifactUrl, getAttachmentUrl, renderKind } from '@/api/signedUrl'

type AttLike = {
  file_key?: string
  artifact_id?: number
  name: string
  type?: string
  mime?: string
  size?: number
  doc_id?: number
  url?: string
}

const props = withDefaults(defineProps<{ att: AttLike; artifact?: boolean }>(), { artifact: false })

const url = ref<string>()
const text = ref<string | null>(null)
const htmlOpen = ref(false)
const htmlUrl = ref<string>()
const textOpen = ref(false)

const kind = computed(() => renderKind(props.att.name, props.att.type))
const ext = computed(() => fileExt(props.att.name))
const isHtml = computed(() => ['html', 'htm'].includes(ext.value))
const isAudio = computed(() => ext.value.startsWith('mp') || ['mp3', 'wav', 'm4a'].includes(ext.value))
const sizeText = computed(() => (fmtSize(props.att.size) ? ` (${fmtSize(props.att.size)})` : ''))

onMounted(async () => {
  try {
    url.value =
      props.artifact && props.att.artifact_id
        ? await getArtifactUrl(props.att.artifact_id)
        : props.att.file_key
          ? await getAttachmentUrl(props.att.file_key)
          : props.att.url
  } catch {
    /* 忽略：链接未就绪时点击下载会再取 */
  }
})

async function download() {
  try {
    const u =
      props.artifact && props.att.artifact_id
        ? await getArtifactUrl(props.att.artifact_id, true)
        : url.value
    if (!u) return
    const a = document.createElement('a')
    a.href = absUrl(u)
    a.download = props.att.name
    if (u.startsWith('http')) a.target = '_blank'
    document.body.appendChild(a)
    a.click()
    a.remove()
  } catch (e: any) {
    ElMessage.error('下载失败')
  }
}

async function openHtml() {
  try {
    const u =
      props.artifact && props.att.artifact_id
        ? await getArtifactUrl(props.att.artifact_id)
        : url.value || (props.att.file_key ? await getAttachmentUrl(props.att.file_key) : undefined)
    if (!u) {
      ElMessage.warning('链接未就绪，请稍候重试')
      return
    }
    htmlUrl.value = absUrl(u)
    htmlOpen.value = true
  } catch {
    ElMessage.error('打开失败')
  }
}

async function openText() {
  const u = url.value
  if (!u) return
  try {
    const resp = await fetch(absUrl(u))
    if (!resp.ok) throw new Error('读取失败')
    text.value = await resp.text()
    textOpen.value = true
  } catch {
    ElMessage.error('读取失败')
  }
}
</script>

<style scoped>
.att-image { border-radius: 8px; margin-top: 6px; display: block; }
.att-audio { margin-top: 6px; max-width: 320px; }
.att-video { max-width: 360px; margin-top: 6px; border-radius: 8px; }
.att-pdf { margin-top: 6px; }
.att-pdf-frame { width: 100%; max-width: 640px; height: 420px; border: 1px solid var(--border); border-radius: 8px; display: block; }
.att-row { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; margin-top: 6px; }
.att-tag { cursor: pointer; display: inline-flex; align-items: center; gap: 4px; }
.att-html-frame { width: 100%; height: 76vh; border: 0; }
.att-text { white-space: pre-wrap; font-size: 13px; margin: 0; font-family: 'SFMono-Regular', Consolas, monospace; }
</style>
