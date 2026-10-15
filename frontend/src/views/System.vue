<template>
  <div class="system-view">
    <div class="page-header">
      <h2 class="page-title">系統設定與管理</h2>
    </div>

    <el-tabs type="border-card">
      <el-tab-pane label="讀卡端管理">
        <el-button @click="fetchDevices">重新整理</el-button>
        <el-table :data="devices" border style="margin-top: 16px">
          <el-table-column prop="name" label="名稱" min-width="130" />
          <el-table-column prop="uuid" label="UUID" min-width="300" />
          <el-table-column label="狀態" width="120">
            <template #default="scope">{{ deviceStatusText(scope.row.status) }}</template>
          </el-table-column>
          <el-table-column label="讀卡" width="90">
            <template #default="scope">{{ scope.row.paused ? '暫停' : '啟用' }}</template>
          </el-table-column>
          <el-table-column prop="last_seen" label="最近連線 (UTC)" min-width="170" />
          <el-table-column label="操作" min-width="370">
            <template #default="scope">
              <el-button size="small" @click="renameDevice(scope.row)">命名</el-button>
              <el-button v-if="scope.row.status === 'pending' || scope.row.status === 'disabled'" size="small" type="success" @click="setDeviceStatus(scope.row, 'approved')">核准</el-button>
              <el-button v-if="scope.row.status === 'approved'" size="small" @click="setDeviceStatus(scope.row, 'disabled')">停用</el-button>
              <el-button v-if="scope.row.status === 'approved'" size="small" @click="sendCommand(scope.row, scope.row.paused ? 'resume' : 'pause')">{{ scope.row.paused ? '恢復讀卡' : '暫停讀卡' }}</el-button>
              <el-button v-if="scope.row.status === 'approved'" size="small" @click="sendCommand(scope.row, 'restart')">重啟程式</el-button>
              <el-button v-if="scope.row.status !== 'revoked'" size="small" type="danger" @click="setDeviceStatus(scope.row, 'revoked')">撤銷</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
      <!-- 頁籤一：帳號管理 -->
      <el-tab-pane label="管理員帳號">
        <div class="header-actions">
          <el-button type="primary" @click="openAddAccountDialog">新增管理帳號</el-button>
        </div>
        <el-table :data="accounts" border style="margin-top: 20px">
          <el-table-column prop="id" label="ID" width="80" />
          <el-table-column prop="username" label="管理員帳號" />
          <el-table-column label="操作" width="250">
            <template #default="scope">
              <el-button size="small" @click="openChangePwdDialog(scope.row.username)">修改密碼</el-button>
              <el-popconfirm 
                title="確定要刪除此管理帳號嗎？" 
                @confirm="handleDeleteAccount(scope.row.username)"
                :disabled="scope.row.username === 'admin'"
              >
                <template #reference>
                  <el-button 
                    size="small" 
                    type="danger" 
                    :disabled="scope.row.username === 'admin'"
                  >刪除</el-button>
                </template>
              </el-popconfirm>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <!-- 頁籤二：系統維護 -->
      <el-tab-pane label="資料庫維護">
        <el-card shadow="never">
          <template #header>資料遷移工具</template>
          <el-alert
            title="此操作會將舊版 SQLite 資料庫的資料匯入當前系統，請確保路徑正確且伺服器有讀取權限。"
            type="warning"
            show-icon
            :closable="false"
            style="margin-bottom: 20px"
          />
          <el-form :inline="true" :model="migrateForm">
            <el-form-item label="舊資料庫路徑">
              <el-input v-model="migrateForm.path" placeholder="例如: C:/old_data/punch.db" style="width: 400px" />
            </el-form-item>
            <el-form-item>
              <el-button type="danger" @click="handleMigrate" :loading="migrating">
                執行合併遷移
              </el-button>
            </el-form-item>
          </el-form>
        </el-card>
      </el-tab-pane>
    </el-tabs>

    <!-- 新增帳號對話框 -->
    <el-dialog v-model="addAccVisible" title="新增管理員" width="400px">
      <el-form :model="addAccForm" label-width="80px">
        <el-form-item label="帳號">
          <el-input v-model="addAccForm.username" />
        </el-form-item>
        <el-form-item label="密碼">
          <el-input v-model="addAccForm.password" type="password" show-password />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="addAccVisible = false">取消</el-button>
        <el-button type="primary" @click="handleAddAccount" :loading="submitting">確定</el-button>
      </template>
    </el-dialog>

    <!-- 修改密碼對話框 -->
    <el-dialog v-model="pwdVisible" title="修改管理員密碼" width="450px">
      <el-form :model="pwdForm" label-width="100px">
        <el-form-item label="管理員帳號">
          <el-input v-model="pwdForm.username" disabled />
        </el-form-item>
        <el-form-item label="舊密碼">
          <el-input v-model="pwdForm.old_password" type="password" show-password />
        </el-form-item>
        <el-form-item label="新密碼">
          <el-input v-model="pwdForm.new_password" type="password" show-password />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="pwdVisible = false">取消</el-button>
        <el-button type="primary" @click="handleChangePassword" :loading="submitting">更新密碼</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import api from '../api'
import { ElMessage, ElMessageBox } from 'element-plus'

const accounts = ref([])
type Device = { uuid: string; name: string; status: string; paused: boolean; last_seen: string | null }
const devices = ref<Device[]>([])
const deviceStatusText = (status: string) => ({ pending: '待審', approved: '已核准', disabled: '已停用', revoked: '已撤銷' }[status] || status)
const fetchDevices = async () => {
  const { data } = await api.get('/devices')
  devices.value = data
}
const renameDevice = async (device: Device) => {
  const { value } = await ElMessageBox.prompt('裝置名稱', '重新命名', { inputValue: device.name, inputPattern: /\S/, inputErrorMessage: '請輸入名稱' })
  await api.patch(`/devices/${device.uuid}`, { name: value.trim() })
  await fetchDevices()
}
const setDeviceStatus = async (device: Device, status: string) => {
  if (status === 'revoked') await ElMessageBox.confirm(`撤銷 ${device.name} 後無法重新啟用，確定嗎？`, '撤銷裝置', { type: 'warning' })
  await api.patch(`/devices/${device.uuid}`, { status })
  await fetchDevices()
}
const sendCommand = async (device: Device, kind: string) => {
  await api.post(`/devices/${device.uuid}/commands`, { kind })
  ElMessage.success(kind === 'restart' ? '重啟指令已排入佇列' : '讀卡狀態已更新')
  await fetchDevices()
}
const submitting = ref(false)
const migrating = ref(false)

// 帳號管理狀態
const addAccVisible = ref(false)
const addAccForm = ref({ username: '', password: '' })
const pwdVisible = ref(false)
const pwdForm = ref({ username: '', old_password: '', new_password: '' })

// 遷移狀態
const migrateForm = ref({ path: '' })

const fetchAccounts = async () => {
  const { data } = await api.get('/accounts')
  accounts.value = data
}

const openAddAccountDialog = () => {
  addAccForm.value = { username: '', password: '' }
  addAccVisible.value = true
}

const handleAddAccount = async () => {
  if (!addAccForm.value.username || !addAccForm.value.password) return ElMessage.warning('請填寫完整資訊')
  submitting.value = true
  try {
    await api.post('/accounts', addAccForm.value)
    ElMessage.success('管理帳號建立成功')
    addAccVisible.value = false
    fetchAccounts()
  } finally {
    submitting.value = false
  }
}

const handleDeleteAccount = async (username: string) => {
  try {
    await api.delete(`/accounts/${username}`)
    ElMessage.success('帳號已刪除')
    fetchAccounts()
  } catch (err) {}
}

const openChangePwdDialog = (username: string) => {
  pwdForm.value = { username, old_password: '', new_password: '' }
  pwdVisible.value = true
}

const handleChangePassword = async () => {
  if (!pwdForm.value.old_password || !pwdForm.value.new_password) return ElMessage.warning('請輸入密碼')
  submitting.value = true
  try {
    await api.put('/accounts/password', pwdForm.value)
    ElMessage.success('密碼修改成功')
    pwdVisible.value = false
  } finally {
    submitting.value = false
  }
}

const handleMigrate = async () => {
  if (!migrateForm.value.path) return ElMessage.warning('請輸入舊資料庫路徑')
  await ElMessageBox.confirm('資料遷移是不可逆的操作，確定要繼續嗎？', '危險操作', { type: 'error' })
  
  migrating.value = true
  try {
    await api.post('/system/migrate', { old_db_path: migrateForm.value.path })
    ElMessage.success('資料遷移完成！')
  } finally {
    migrating.value = false
  }
}

onMounted(() => { fetchAccounts(); fetchDevices() })
</script>

<style scoped>
.page-header {
  padding: 15px 25px;
  background: linear-gradient(to right, #ffffff, #ede9e1);
  border-left: 6px solid #A27B5C;
  margin-bottom: 25px;
  border-radius: 8px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.05);
}
.page-title {
  margin: 0;
  font-size: 24px;
  font-weight: 800;
  color: #1f2f3d;
}
.header-actions {
  margin-bottom: 15px;
}
</style>
