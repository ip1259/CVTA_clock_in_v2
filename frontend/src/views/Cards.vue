<template>
  <div class="cards-view">
    <div class="page-header">
      <h2 class="page-title">卡片管理系統</h2>
      <div>
        <el-button type="primary" :disabled="enrollPending" @click="openEnrollDialog">新增卡片</el-button>
        <el-button @click="fetchCards" :loading="loading" circle :icon="Refresh" type="primary" plain />
      </div>
    </div>

    <el-dialog v-model="enrollVisible" title="新增卡片" width="440px">
      <p>選擇讀卡端。命令送達後，請在讀卡端顯示加卡模式的 30 秒內刷一張卡。</p>
      <el-select v-model="selectedDevice" placeholder="選擇已核准讀卡端" style="width: 100%">
        <el-option v-for="device in approvedDevices" :key="device.uuid"
          :label="`${device.name} (${device.uuid})${device.paused ? ' — 已暫停' : ''}`"
          :value="device.uuid" :disabled="device.paused" />
      </el-select>
      <template #footer>
        <el-button @click="enrollVisible = false">取消</el-button>
        <el-button type="primary" :disabled="!selectedDevice" :loading="sending" @click="sendEnrollCommand">發送加卡命令</el-button>
      </template>
    </el-dialog>

    <el-alert v-if="enrollResult" :title="enrollResultTitle" :type="enrollResultType"
      :closable="false" show-icon style="margin-bottom: 20px">
      <template #default>
        <span>{{ enrollResultDetail }}</span>
        <el-button v-if="enrollQueryFailed" size="small" @click="pollEnrollResult">重試查詢</el-button>
      </template>
    </el-alert>

    <el-table :data="cards" v-loading="loading" style="width: 100%; margin-top: 20px" border>
      <el-table-column prop="id" label="ID" width="80" />
      <el-table-column prop="uid" label="卡號 (UID)" />
      <el-table-column label="目前擁有者">
        <template #default="scope">
          <el-tag v-if="scope.row.owner_name" type="success">{{ scope.row.owner_name }}</el-tag>
          <el-tag v-else type="info">尚未分配</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="220">
        <template #default="scope">
          <el-button 
            v-if="scope.row.employee_id" 
            size="small" 
            type="warning" 
            @click="handleUnbind(scope.row)"
          >
            解除綁定
          </el-button>
          <el-popconfirm title="確定要永久刪除此卡片紀錄嗎？" @confirm="handleDelete(scope.row)">
            <template #reference>
              <el-button size="small" type="danger">刪除</el-button>
            </template>
          </el-popconfirm>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, onMounted, onUnmounted } from 'vue'
import api from '../api'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'

interface Card {
  id: number
  uid: string
  employee_id: number | null
  owner_name: string | null
}
interface Device { uuid: string; name: string; status: string; paused: boolean }
interface EnrollmentResult { id: number; status: string; uid: string | null; expires_at: string }

const cards = ref<Card[]>([])
const loading = ref(false)
const enrollVisible = ref(false)
const selectedDevice = ref('')
const approvedDevices = ref<Device[]>([])
const sending = ref(false)
const enrollResult = ref<EnrollmentResult | null>(null)
const enrollDevice = ref('')
const enrollQueryFailed = ref(false)
let enrollTimer: ReturnType<typeof setTimeout> | undefined
let enrollRequestId = 0

const enrollPending = computed(() => !!enrollResult.value &&
  ['pending_delivery', 'waiting_for_card'].includes(enrollResult.value.status))
const enrollResultType = computed<'success' | 'warning' | 'error' | 'info'>(() => {
  if (enrollQueryFailed.value) return 'warning'
  if (enrollResult.value?.status === 'succeeded') return 'success'
  if (enrollResult.value?.status === 'duplicate' || enrollResult.value?.status === 'expired') return 'error'
  return 'info'
})
const enrollResultTitle = computed(() => {
  if (enrollQueryFailed.value) return '新增結果暫時無法查詢'
  switch (enrollResult.value?.status) {
    case 'pending_delivery': return '等待讀卡端接收命令'
    case 'waiting_for_card': return '讀卡端已進入新增卡片模式'
    case 'succeeded': return '新增卡片成功'
    case 'duplicate': return '新增卡片失敗：卡號已存在'
    case 'expired': return '新增卡片未完成'
    default: return '查詢新增結果中'
  }
})
const enrollResultDetail = computed(() => {
  if (enrollQueryFailed.value) return '請重試查詢；刷卡請求可能已送達，勿直接重複新增。'
  const uid = enrollResult.value?.uid
  if (uid) return `卡號 ${uid}。${enrollResult.value?.status === 'succeeded' ? '已更新卡片清單。' : '請核對現有卡片。'}`
  if (enrollResult.value?.status === 'waiting_for_card') return '請在讀卡端顯示加卡模式的 30 秒內刷一張卡。'
  if (enrollResult.value?.status === 'expired') return '未在有效時間內完成，或命令已被取消；若曾刷卡但網路中斷，請先核對卡片清單。'
  return '命令已排入佇列，請等待讀卡端顯示加卡模式。'
})

const pollEnrollResult = async () => {
  const result = enrollResult.value
  if (!result) return
  const requestId = enrollRequestId
  enrollQueryFailed.value = false
  try {
    const { data } = await api.get<EnrollmentResult>(`/devices/${enrollDevice.value}/commands/${result.id}`)
    if (requestId !== enrollRequestId) return
    const previous = enrollResult.value?.status
    enrollResult.value = data
    if (data.status === 'succeeded' && previous !== 'succeeded') {
      ElMessage.success(`卡號 ${data.uid} 新增成功`)
      fetchCards().catch(() => {
        // The command result remains successful even if refreshing the list fails.
      })
    } else if (data.status === 'duplicate' && previous !== 'duplicate') {
      ElMessage.error(`卡號 ${data.uid} 已存在，新增失敗`)
    } else if (data.status === 'expired' && previous !== 'expired') {
      ElMessage.warning('加卡命令逾時或已取消')
    }
    if (['pending_delivery', 'waiting_for_card'].includes(data.status)) {
      enrollTimer = setTimeout(pollEnrollResult, 1000)
    }
  } catch {
    if (requestId === enrollRequestId) enrollQueryFailed.value = true
  }
}

const openEnrollDialog = async () => {
  selectedDevice.value = ''
  const { data } = await api.get<Device[]>('/devices')
  approvedDevices.value = data.filter(device => device.status === 'approved')
  enrollVisible.value = true
}

const sendEnrollCommand = async () => {
  if (!selectedDevice.value) return
  sending.value = true
  try {
    const { data } = await api.post<{ id: number }>(`/devices/${selectedDevice.value}/commands`, { kind: 'enroll_card' })
    if (enrollTimer) clearTimeout(enrollTimer)
    enrollRequestId += 1
    enrollDevice.value = selectedDevice.value
    enrollResult.value = { id: data.id, status: 'pending_delivery', uid: null, expires_at: '' }
    enrollVisible.value = false
    pollEnrollResult()
  } finally {
    sending.value = false
  }
}

const fetchCards = async () => {
  loading.value = true
  try {
    const { data } = await api.get('/cards')
    cards.value = data
  } finally {
    loading.value = false
  }
}

const handleUnbind = async (row: Card) => {
  try {
    await ElMessageBox.confirm(
      `確定要解除卡片 ${row.uid} 與員工 ${row.owner_name} 的綁定嗎？`,
      '警告',
      { type: 'warning' }
    )
    await api.put(`/cards/${row.id}/unbind`)
    ElMessage.success('已成功解除綁定')
    fetchCards()
  } catch (err) {
    if (err !== 'cancel') console.error(err)
  }
}

const handleDelete = async (row: Card) => {
  try {
    await api.delete(`/cards/${row.id}`)
    ElMessage.success('卡片已刪除')
    fetchCards()
  } catch (error) {
    // 錯誤已由攔截器處理
  }
}

onMounted(() => {
  fetchCards()
})
onUnmounted(() => {
  enrollRequestId += 1
  if (enrollTimer) clearTimeout(enrollTimer)
})
</script>

<style scoped>
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
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
  color: var(--el-text-color-primary);
  letter-spacing: 1px;
}
</style>
