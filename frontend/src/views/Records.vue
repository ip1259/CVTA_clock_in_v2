<template>
  <div class="records-view">
    <div class="page-header">
      <h2 class="page-title">考勤報表</h2>
    </div>

    <el-tabs type="border-card">
      <!-- 頁籤一：打卡紀錄檢視 -->
      <el-tab-pane label="打卡紀錄檢視">
        <div class="filter-container">
          <el-form :inline="true" :model="queryForm">
            <el-form-item label="員工">
              <el-select v-model="queryForm.employeeId" placeholder="請選擇員工" style="width: 150px">
                <el-option v-for="e in employees" :key="e.id" :label="e.name" :value="e.id" />
              </el-select>
            </el-form-item>
            <el-form-item label="日期範圍">
              <el-date-picker
                v-model="queryForm.dateRange"
                type="daterange"
                range-separator="至"
                start-placeholder="開始日期"
                end-placeholder="結束日期"
                value-format="YYYY-MM-DD"
              />
            </el-form-item>
            <el-form-item>
              <el-button type="primary" @click="fetchRecords" :loading="querying">查詢</el-button>
              <el-button type="success" plain @click="openManualDialog">手動補打卡</el-button>
            </el-form-item>
          </el-form>
        </div>
        <el-table :data="recordData" border stripe style="width: 100%; margin-top: 10px">
          <el-table-column prop="record_time" label="打卡時間" sortable />
          <el-table-column prop="uid" label="卡號 (UID)" />
          <el-table-column prop="note" label="備註/事由" />
          <el-table-column prop="id" label="ID" width="80" />
        </el-table>
      </el-tab-pane>

      <!-- 頁籤二：報表匯出 -->
      <el-tab-pane label="報表匯出">
        <el-card shadow="never">
          <el-form :model="exportForm" label-width="100px">
            <el-form-item label="選取月份">
              <el-date-picker
                v-model="exportForm.month"
                type="month"
                placeholder="選擇月份"
                value-format="YYYY-MM"
              />
            </el-form-item>
            <el-form-item label="選取員工">
              <el-select
                v-model="exportForm.employeeIds"
                multiple
                collapse-tags
                placeholder="請選擇員工 (可多選)"
                style="width: 300px"
              >
                <el-option
                  v-for="item in employees"
                  :key="item.id"
                  :label="item.name"
                  :value="item.id"
                />
              </el-select>
              <el-button type="info" link @click="selectAllEmployees">全選</el-button>
            </el-form-item>
            <el-form-item>
              <el-button type="primary" :icon="Download" @click="handleExport" :loading="exporting">
                產生並下載報表
              </el-button>
            </el-form-item>
          </el-form>
        </el-card>
      </el-tab-pane>
    </el-tabs>

    <!-- 手動補打卡對話框 -->
    <el-dialog v-model="manualDialogVisible" title="管理員手動補打卡" width="500px">
      <el-form :model="manualForm" label-width="100px">
        <el-form-item label="選擇員工" required>
          <el-select v-model="manualForm.employeeId" placeholder="請選擇員工" style="width: 100%">
            <el-option v-for="e in employees" :key="e.id" :label="e.name" :value="e.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="打卡時間" required>
          <el-date-picker
            v-model="manualForm.recordTime"
            type="datetime"
            placeholder="選擇日期時間"
            value-format="YYYY-MM-DD HH:mm:ss"
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item label="補打卡事由" required>
          <el-select v-model="manualForm.reasonType" placeholder="請選擇常用事由" style="width: 100%">
            <el-option label="打卡程式異常" value="打卡程式異常" />
            <el-option label="忘記帶卡" value="忘記帶卡" />
            <el-option label="卡片遺失" value="卡片遺失" />
            <el-option label="補紀錄 (漏刷)" value="補紀錄 (漏刷)" />
            <el-option label="其他" value="其他" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="manualForm.reasonType === '其他'" label="自定義事由" required>
          <el-input v-model="manualForm.customReason" type="textarea" placeholder="請輸入詳細事由" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="manualDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitManualRecord" :loading="submitting">
          確認提交
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import api from '../api'
import { ElMessage } from 'element-plus'
import { Download} from '@element-plus/icons-vue'

const employees = ref<any[]>([])
const exporting = ref(false)
const querying = ref(false)
const recordData = ref([])

const queryForm = ref({
  employeeId: null,
  dateRange: [] as string[]
})

const manualDialogVisible = ref(false)
const submitting = ref(false)
const manualForm = ref({
  employeeId: null as number | null,
  recordTime: '',
  reasonType: '',
  customReason: ''
})

const exportForm = ref({
  month: '',
  employeeIds: [] as number[]
})

const fetchEmployees = async () => {
  const { data } = await api.get('/employees')
  employees.value = data
}

const selectAllEmployees = () => {
  exportForm.value.employeeIds = employees.value.map(e => e.id)
}

const fetchRecords = async () => {
  if (!queryForm.value.employeeId || !queryForm.value.dateRange || queryForm.value.dateRange.length === 0) {
    return ElMessage.warning('請選擇員工與日期範圍')
  }

  querying.value = true
  try {
    const { data } = await api.get('/records', {
      params: {
        employee_id: queryForm.value.employeeId,
        start_date: queryForm.value.dateRange[0],
        end_date: queryForm.value.dateRange[1]
      }
    })
    recordData.value = data
  } finally {
    querying.value = false
  }
}

const openManualDialog = () => {
  manualForm.value = {
    employeeId: queryForm.value.employeeId,
    recordTime: new Date().toISOString().slice(0, 19).replace('T', ' '),
    reasonType: '',
    customReason: ''
  }
  manualDialogVisible.value = true
}

const submitManualRecord = async () => {
  const { employeeId, recordTime, reasonType, customReason } = manualForm.value
  if (!employeeId || !recordTime || !reasonType) {
    return ElMessage.warning('請填寫完整資訊')
  }

  const finalNote = reasonType === '其他' ? customReason : reasonType
  if (!finalNote) return ElMessage.warning('請輸入自定義事由')

  submitting.value = true
  try {
    await api.post('/records/manual', {
      employee_id: employeeId,
      record_time: recordTime,
      note: `[手動] ${finalNote}`
    })
    ElMessage.success('手動打卡紀錄已新增')
    manualDialogVisible.value = false
    fetchRecords() // 重新整理清單
  } finally {
    submitting.value = false
  }
}

const handleExport = async () => {
  if (!exportForm.value.month || exportForm.value.employeeIds.length === 0) {
    return ElMessage.warning('請選擇月份與至少一位員工')
  }
  
  exporting.value = true
  try {
    const [year, month] = exportForm.value.month.split('-')
    
    // 手動建構查詢參數，避免 Axios 預設的陣列序列化問題 (employee_ids[])
    const params = new URLSearchParams()
    params.append('year', year)
    params.append('month', month)
    exportForm.value.employeeIds.forEach(id => params.append('employee_ids', id.toString()))

    const response = await api.get('/export/attendance', {
      params,
      responseType: 'blob'
    })
    
    const url = window.URL.createObjectURL(new Blob([response.data]))
    const link = document.createElement('a')
    link.href = url
    link.setAttribute('download', `Attendance_${year}_${month}.xlsx`)
    document.body.appendChild(link)
    link.click()
    link.remove()
  } finally {
    exporting.value = false
  }
}

onMounted(fetchEmployees)
</script>

<style scoped>
.page-header {
  display: flex;
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
  color: #1f2f3d;
}

.box-card {
  max-width: 1000px;
  margin: 0 auto;
}
.card-header {
  font-weight: bold;
}
</style>