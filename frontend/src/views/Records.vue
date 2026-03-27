<template>
  <div class="records-view">
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
            </el-form-item>
          </el-form>
        </div>
        <el-table :data="recordData" border stripe style="width: 100%; margin-top: 10px">
          <el-table-column prop="record_time" label="打卡時間" sortable />
          <el-table-column prop="uid" label="卡號 (UID)" />
          <el-table-column prop="id" label="系統 ID" width="100" />
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
              <el-button type="primary" icon="Download" @click="handleExport" :loading="exporting">
                產生並下載報表
              </el-button>
            </el-form-item>
          </el-form>
        </el-card>
      </el-tab-pane>

      <!-- 頁籤三：系統維護 -->
      <el-tab-pane label="系統維護">
        <el-card shadow="never">
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
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import api from '../api'
import { ElMessage, ElMessageBox } from 'element-plus'

const employees = ref<any[]>([])
const exporting = ref(false)
const migrating = ref(false)
const querying = ref(false)
const recordData = ref([])

const queryForm = ref({
  employeeId: null,
  dateRange: [] as string[]
})

const exportForm = ref({
  month: '',
  employeeIds: [] as number[]
})

const migrateForm = ref({
  path: ''
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

const handleMigrate = async () => {
  if (!migrateForm.value.path) return ElMessage.warning('請輸入舊資料庫路徑')
  
  await ElMessageBox.confirm('遷移資料庫是不可逆的操作，確定要繼續嗎？', '確認遷移', { type: 'error' })
  
  migrating.value = true
  try {
    await api.post('/system/migrate', { old_db_path: migrateForm.value.path })
    ElMessage.success('資料遷移成功！')
  } finally {
    migrating.value = false
  }
}

onMounted(fetchEmployees)
</script>

<style scoped>
.box-card {
  max-width: 1000px;
  margin: 0 auto;
}
.card-header {
  font-weight: bold;
}
</style>