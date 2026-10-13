<template>
  <PageContainer title="数据库与运维" subtitle="查看运行环境、切换数据库、备份恢复与维护操作">
    <template #extra>
      <el-button :icon="Refresh" @click="loadAll">刷新</el-button>
    </template>

    <!-- 信息卡 -->
    <div class="app-card panel" style="margin-bottom: 16px">
      <div class="info-head">
        <span class="info-title">运行信息</span>
        <el-tag v-if="info" size="small" :type="info.driver_ok ? 'success' : 'danger'">
          驱动{{ info.driver_ok ? '正常' : '缺失' }}
        </el-tag>
      </div>
      <el-skeleton v-if="loading" :rows="3" animated />
      <el-descriptions v-else-if="info" :column="3" border size="small">
        <el-descriptions-item label="数据库类型">{{ info.db_kind }}</el-descriptions-item>
        <el-descriptions-item label="数据库地址"><span class="mono">{{ info.db_url_masked }}</span></el-descriptions-item>
        <el-descriptions-item label="表数量">{{ info.table_count }}</el-descriptions-item>
        <el-descriptions-item label="数据目录">{{ fmtSize(info.data_dir_size) }}</el-descriptions-item>
        <el-descriptions-item label="文件目录">{{ fmtSize(info.files_dir_size) }}</el-descriptions-item>
        <el-descriptions-item label="运行时长">{{ fmtUptime(info.uptime_seconds) }}</el-descriptions-item>
        <el-descriptions-item label="向量后端">{{ info.vector_backend }}</el-descriptions-item>
        <el-descriptions-item label="任务后端">{{ info.task_backend }}</el-descriptions-item>
        <el-descriptions-item label="Python">{{ info.python }}</el-descriptions-item>
        <el-descriptions-item label="平台" :span="2">{{ info.platform }}</el-descriptions-item>
        <el-descriptions-item label="打包运行">{{ info.frozen ? '是' : '否' }}</el-descriptions-item>
      </el-descriptions>
      <el-empty v-else description="无法获取系统信息" :image-size="60" />
    </div>

    <!-- 数据库驱动 -->
    <div class="app-card panel" style="margin-bottom: 16px">
      <div class="sec-head">
        <span class="sec-title">数据库驱动</span>
        <el-button size="small" :loading="driversLoading" @click="loadDrivers">检测</el-button>
      </div>
      <el-table v-if="Object.keys(drivers).length" :data="driverRows" size="small">
        <el-table-column prop="kind" label="数据库类型" width="140" />
        <el-table-column prop="packages" label="依赖包" show-overflow-tooltip />
        <el-table-column label="状态" width="110">
          <template #default="{ row }"><el-tag size="small" :type="row.ok ? 'success' : 'danger'">{{ row.ok ? '已安装' : '缺失' }}</el-tag></template>
        </el-table-column>
        <el-table-column label="操作" width="130">
          <template #default="{ row }">
            <el-button v-if="!row.ok" size="small" :loading="installing === row.kind" @click="installDriver(row.kind)">安装驱动</el-button>
            <span v-else class="text-muted">—</span>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-else description="点「检测」查看各数据库驱动状态" :image-size="50" />
      <pre v-if="installMsg" class="drv-log">{{ installMsg }}</pre>
    </div>

    <el-row :gutter="16">
      <!-- 数据库切换 -->
      <el-col :xs="24" :lg="12">
        <div class="app-card panel" style="margin-bottom: 16px">
          <div class="sec-title">数据库连接</div>
          <el-input v-model="dbUrl" placeholder="如 sqlite:///data/app.db 或 postgresql://..." class="mono-input">
            <template #prepend>DATABASE_URL</template>
          </el-input>
          <div class="btn-row">
            <el-button :loading="dbBusy === 'test'" @click="testDb">测试连接</el-button>
            <el-button :loading="dbBusy === 'init'" type="primary" plain @click="initDb">初始化</el-button>
            <el-button :loading="dbBusy === 'save'" type="warning" plain @click="saveRestart">保存并重启</el-button>
          </div>
          <el-alert v-if="dbMsg" :type="dbOk ? 'success' : 'error'" :closable="false" :title="dbMsg" style="margin-top: 10px" />
        </div>
      </el-col>

      <!-- 维护操作 -->
      <el-col :xs="24" :lg="12">
        <div class="app-card panel" style="margin-bottom: 16px">
          <div class="sec-title">维护操作</div>
          <div class="ops-grid">
            <el-button :loading="busy === 'migrate'" @click="migrate">数据库迁移</el-button>
            <el-button :loading="busy === 'seed'" @click="seed">播种初始数据</el-button>
            <el-button @click="resetPwd">重置管理员密码</el-button>
            <el-button @click="cleanup">清理数据</el-button>
            <el-button type="danger" plain :loading="busy === 'reset'" @click="resetAll">重置全部数据</el-button>
          </div>
        </div>
      </el-col>
    </el-row>

    <!-- 备份 -->
    <div class="app-card panel">
      <div class="sec-head">
        <span class="sec-title">数据库备份</span>
        <div>
          <el-upload
            :show-file-list="false"
            :auto-upload="false"
            :on-change="onRestoreFile"
            accept=".db,.sqlite,.sqlite3,.backup,.bak,.gz,.zip"
            style="display: inline-block; margin-right: 8px"
          >
            <el-button :icon="Upload">上传恢复</el-button>
          </el-upload>
          <el-button type="primary" :icon="Plus" :loading="busy === 'backup'" @click="createBackup">新建备份</el-button>
        </div>
      </div>
      <el-table v-loading="backupLoading" :data="backups" row-key="name">
        <el-table-column prop="name" label="文件名" min-width="240" show-overflow-tooltip />
        <el-table-column label="大小" width="120">
          <template #default="{ row }">{{ fmtSize(row.size) }}</template>
        </el-table-column>
        <el-table-column label="创建时间" width="180">
          <template #default="{ row }">{{ fmtTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="160" fixed="right">
          <template #default="{ row }">
            <el-button size="small" @click="download(row)">下载</el-button>
            <el-popconfirm :title="`删除备份 ${row.name}？`" @confirm="removeBackup(row)">
              <template #reference><el-button size="small" danger :icon="Delete" /></template>
            </el-popconfirm>
          </template>
        </el-table-column>
      </el-table>
    </div>
  </PageContainer>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh, Plus, Delete, Upload } from '@element-plus/icons-vue'
import PageContainer from '@/components/PageContainer.vue'
import { systemOpsApi, withToken, type SystemInfo } from '@/api'
import { errMsg } from '@/api/http'

const loading = ref(true)
const info = ref<SystemInfo | null>(null)

const dbUrl = ref('')
const dbBusy = ref('')
const dbMsg = ref('')
const dbOk = ref(false)

const backups = ref<{ name: string; size: number; created_at: number }[]>([])
const backupLoading = ref(false)
const busy = ref('')

const drivers = ref<Record<string, { packages: string[]; ok: boolean }>>({})
const driversLoading = ref(false)
const installing = ref('')
const installMsg = ref('')
const driverRows = ref<{ kind: string; packages: string; ok: boolean }[]>([])

async function loadDrivers() {
  driversLoading.value = true
  try {
    drivers.value = await systemOpsApi.drivers()
    driverRows.value = Object.entries(drivers.value).map(([kind, v]) => ({ kind, packages: (v.packages || []).join(', '), ok: !!v.ok }))
  } catch (e) { ElMessage.error(errMsg(e)) } finally { driversLoading.value = false }
}
async function installDriver(kind: string) {
  installing.value = kind
  installMsg.value = ''
  try {
    const r = await systemOpsApi.installDriver(kind)
    installMsg.value = r.log || r.message || ''
    ElMessage[r.ok ? 'success' : 'warning'](r.message || '已执行')
    loadDrivers()
  } catch (e) { ElMessage.error(errMsg(e)) } finally { installing.value = '' }
}

function fmtSize(n?: number) {
  if (!n || n <= 0) return '0 B'
  const u = ['B', 'KB', 'MB', 'GB', 'TB']
  let i = 0
  let v = n
  while (v >= 1024 && i < u.length - 1) { v /= 1024; i++ }
  return `${v.toFixed(v < 10 && i > 0 ? 1 : 0)} ${u[i]}`
}
function fmtUptime(s?: number) {
  if (!s || s <= 0) return '—'
  const d = Math.floor(s / 86400)
  const h = Math.floor((s % 86400) / 3600)
  const m = Math.floor((s % 3600) / 60)
  if (d) return `${d} 天 ${h} 小时`
  if (h) return `${h} 小时 ${m} 分`
  return `${m} 分钟`
}
function fmtTime(ts?: number) {
  if (!ts) return '—'
  const d = new Date(ts < 1e12 ? ts * 1000 : ts)
  if (Number.isNaN(d.getTime())) return '—'
  const p = (x: number) => String(x).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
}

async function loadInfo() {
  loading.value = true
  try { info.value = await systemOpsApi.info() } catch (e) { ElMessage.error(errMsg(e)) } finally { loading.value = false }
}
async function loadBackups() {
  backupLoading.value = true
  try { backups.value = await systemOpsApi.listBackups().catch(() => []) } catch (e) { ElMessage.error(errMsg(e)) } finally { backupLoading.value = false }
}
function loadAll() { loadInfo(); loadBackups(); loadDrivers() }

// ---- 数据库 ----
async function testDb() {
  if (!dbUrl.value.trim()) { ElMessage.warning('请输入 database_url'); return }
  dbBusy.value = 'test'
  dbMsg.value = ''
  try {
    const r = await systemOpsApi.testDb(dbUrl.value.trim())
    dbOk.value = r.ok
    dbMsg.value = r.ok ? `连接成功：${r.message}` : `连接失败：${r.message}${r.driver_missing?.length ? `（缺少驱动：${r.driver_missing.join(', ')}）` : ''}`
  } catch (e) { dbOk.value = false; dbMsg.value = errMsg(e) } finally { dbBusy.value = '' }
}
async function initDb() {
  if (!dbUrl.value.trim()) { ElMessage.warning('请输入 database_url'); return }
  try {
    await ElMessageBox.confirm('将在目标数据库初始化建表。若库中已有数据请谨慎操作，继续？', '初始化数据库', { type: 'warning' })
  } catch { return }
  dbBusy.value = 'init'
  try {
    const r = await systemOpsApi.initDb(dbUrl.value.trim())
    ElMessage.success(r.message || `初始化完成（${r.table_count ?? 0} 张表）`)
    loadInfo()
  } catch (e) { ElMessage.error(errMsg(e)) } finally { dbBusy.value = '' }
}
async function saveRestart() {
  if (!dbUrl.value.trim()) { ElMessage.warning('请输入 database_url'); return }
  try {
    await ElMessageBox.confirm('保存数据库地址并重启服务？重启期间服务会短暂中断。', '保存并重启', { type: 'warning' })
  } catch { return }
  dbBusy.value = 'save'
  try { const r = await systemOpsApi.saveRestart(dbUrl.value.trim()); ElMessage.success(r.message || '已保存，正在重启') } catch (e) { ElMessage.error(errMsg(e)) } finally { dbBusy.value = '' }
}

// ---- 维护 ----
async function migrate() {
  busy.value = 'migrate'
  try { const r = await systemOpsApi.migrate(); ElMessage.success(r.message || '迁移完成'); loadInfo() } catch (e) { ElMessage.error(errMsg(e)) } finally { busy.value = '' }
}
async function seed() {
  try { await ElMessageBox.confirm('将写入初始种子数据，继续？', '播种数据', { type: 'warning' }) } catch { return }
  busy.value = 'seed'
  try { const r = await systemOpsApi.seed(); ElMessage.success(r.message || '已完成') } catch (e) { ElMessage.error(errMsg(e)) } finally { busy.value = '' }
}
async function resetAll() {
  try {
    await ElMessageBox.confirm('此操作将清空并重置全部数据，且不可恢复！确认继续？', '重置全部数据', {
      type: 'error', confirmButtonText: '我确认重置', cancelButtonText: '取消', confirmButtonClass: 'el-button--danger',
    })
  } catch { return }
  busy.value = 'reset'
  try { const r = await systemOpsApi.reset(); ElMessage.success(r.message || '已重置'); loadInfo() } catch (e) { ElMessage.error(errMsg(e)) } finally { busy.value = '' }
}
async function resetPwd() {
  let user = ''
  let pwd = ''
  try {
    const r = await ElMessageBox.prompt('请输入管理员用户名', '重置管理员密码', {
      inputValue: 'admin', inputPlaceholder: 'admin',
      inputValidator: (v: string) => (v && v.trim() ? true : '请输入用户名'),
    })
    user = r.value.trim()
  } catch { return }
  try {
    const r = await ElMessageBox.prompt('请输入新密码', `重置「${user}」的密码`, {
      inputType: 'password', inputPlaceholder: '至少 6 位',
      inputValidator: (v: string) => (v && v.length >= 6 ? true : '密码至少 6 位'),
    })
    pwd = r.value
  } catch { return }
  try { const r = await systemOpsApi.resetAdminPassword(user, pwd); ElMessage.success(r.message || '密码已重置') } catch (e) { ElMessage.error(errMsg(e)) }
}
async function cleanup() {
  let scope = 'all'
  const scopes = [
    { value: 'all', label: '全部（日志/临时文件/缓存）' },
    { value: 'logs', label: '仅日志' },
    { value: 'temp', label: '仅临时文件' },
    { value: 'files', label: '仅孤儿文件' },
  ]
  try {
    const { value } = await ElMessageBox.prompt('选择清理范围：all / logs / temp / files', '清理数据', {
      inputValue: 'all',
      inputValidator: (v: string) => (scopes.some((s) => s.value === (v || '').trim()) ? true : '请输入有效范围'),
    })
    scope = (value || 'all').trim()
  } catch { return }
  try {
    const r = await systemOpsApi.cleanup(scope)
    ElMessage.success(`${r.message || '清理完成'}（删除 ${r.removed} 项，释放 ${fmtSize(r.freed_bytes)}）`)
    loadInfo()
  } catch (e) { ElMessage.error(errMsg(e)) }
}

// ---- 备份 ----
async function createBackup() {
  busy.value = 'backup'
  try { const r = await systemOpsApi.createBackup(); ElMessage.success(r.message || `已创建备份 ${r.name}`); loadBackups() } catch (e) { ElMessage.error(errMsg(e)) } finally { busy.value = '' }
}
function download(row: { name: string }) {
  window.open(withToken(systemOpsApi.backupDownloadUrl(row.name)), '_blank')
}
async function removeBackup(row: { name: string }) {
  try { const r = await systemOpsApi.deleteBackup(row.name); ElMessage.success(r.message || '已删除'); loadBackups() } catch (e) { ElMessage.error(errMsg(e)) }
}
async function onRestoreFile(file: any) {
  const f: File | undefined = file?.raw
  if (!f) return
  try {
    await ElMessageBox.confirm(`将用上传文件「${f.name}」覆盖当前数据库，操作不可恢复。确认继续？`, '恢复数据库', {
      type: 'error', confirmButtonText: '确认恢复', confirmButtonClass: 'el-button--danger',
    })
  } catch { return }
  try {
    const r = await systemOpsApi.restore(f)
    ElMessage.success(r.message || '恢复完成')
    loadInfo()
  } catch (e) { ElMessage.error(errMsg(e)) }
}

onMounted(loadAll)
</script>

<style scoped>
.panel { padding: 18px 20px; }
.info-head { display: flex; align-items: center; gap: 10px; margin-bottom: 12px; }
.info-title, .sec-title { font-size: 15px; font-weight: 600; color: var(--text-title); }
.sec-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
.mono, .mono-input :deep(input) { font-family: monospace; font-size: 12px; }
.btn-row { display: flex; gap: 8px; margin-top: 12px; flex-wrap: wrap; }
.drv-log { margin-top: 10px; max-height: 220px; overflow: auto; background: var(--bg-subtle); border: 1px solid var(--border); border-radius: 8px; padding: 10px; font-size: 12px; white-space: pre-wrap; font-family: monospace; }
.ops-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 10px; }
.ops-grid .el-button { margin: 0; width: 100%; }
</style>
