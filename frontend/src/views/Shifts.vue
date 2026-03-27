<template>
  <div class="shifts-view">
    <el-tabs type="border-card">
      <!-- 頁籤一：日曆排班 -->
      <el-tab-pane label="日曆排班">
        <div class="header-actions">
          <el-form :inline="true">
            <el-form-item label="管理員工">
              <el-select 
                v-model="selectedEmployeeId" 
                placeholder="請選擇員工" 
                @change="fetchMonthlyData"
                style="width: 200px"
              >
                <el-option
                  v-for="item in employees"
                  :key="item.id"
                  :label="item.name + (item.nickname ? ` (${item.nickname})` : '')"
                  :value="item.id"
                />
              </el-select>
            </el-form-item>
            <el-form-item>
              <el-button type="primary" plain icon="Refresh" @click="fetchMonthlyData" :disabled="!selectedEmployeeId">
                重新整理
              </el-button>
              <el-button type="warning" plain icon="Calendar" @click="handleSyncHolidays">
                手動更新假日資料
              </el-button>
            </el-form-item>
          </el-form>
        </div>

        <el-calendar v-if="selectedEmployeeId" v-model="viewDate" v-loading="loading">
          <template #date-cell="{ data }">
            <div class="calendar-cell" @click="handleDateClick(data.day)">
              <div class="cell-header">
                <span class="day-number">{{ data.day.split('-').slice(2).join('') }}</span>
                <el-tag v-if="getShift(data.day)?.is_leave" size="small" type="danger" effect="dark" class="manual-tag">請假</el-tag>
                <el-tag v-else-if="getShift(data.day)?.is_manual" size="small" type="warning" effect="plain" class="manual-tag">手動</el-tag>
              </div>
              <div v-if="getShift(data.day)" class="shift-content">
                <span v-if="getShift(data.day).schedule" class="shift-name">
                  {{ getShift(data.day).schedule.name }}
                </span>
                <span v-else class="holiday-text">{{ getShift(data.day).is_leave ? '請假/排休' : '休假' }}</span>
              </div>
            </div>
          </template>
        </el-calendar>
        <el-empty v-else description="請先選擇員工以管理排班" />
      </el-tab-pane>

      <!-- 頁籤二：班表樣板管理 -->
      <el-tab-pane label="樣板管理">
        <div class="header-actions">
          <el-button type="primary" icon="Plus" @click="openTemplateDialog">新增班表樣板</el-button>
        </div>
        <el-table :data="schedules" border style="margin-top: 20px">
          <el-table-column prop="name" label="班表名稱" />
          <el-table-column prop="start" label="上班時間" />
          <el-table-column prop="end" label="下班時間" />
          <el-table-column label="操作" width="120">
            <template #default="scope">
              <el-popconfirm title="確定要刪除此樣板嗎？" @confirm="handleDeleteTemplate(scope.row.id)">
                <template #reference>
                  <el-button type="danger" size="small" icon="Delete" circle />
                </template>
              </el-popconfirm>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
    </el-tabs>

    <!-- 新增樣板對話框 -->
    <el-dialog v-model="templateDialogVisible" title="新增班表樣板" width="400px">
      <el-form :model="templateForm" label-width="100px">
        <el-form-item label="樣板名稱" required>
          <el-input v-model="templateForm.name" placeholder="例如：早班、大夜" />
        </el-form-item>
        <el-form-item label="上班時間" required>
          <el-time-select
            v-model="templateForm.job_start"
            start="00:00" step="00:15" end="23:45"
            placeholder="開始時間"
          />
        </el-form-item>
        <el-form-item label="下班時間" required>
          <el-time-select
            v-model="templateForm.job_end"
            start="00:00" step="00:15" end="23:45"
                placeholder="結束時間"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="templateDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitTemplate" :loading="submitting">儲存樣板</el-button>
      </template>
    </el-dialog>

    <!-- 修改排班對話框 -->
    <el-dialog v-model="dialogVisible" title="修改排班" width="400px">
      <el-form label-width="80px">
        <el-form-item label="目標日期">
          <el-input :model-value="editForm.date" disabled />
        </el-form-item>
        <el-form-item label="班表樣板">
          <el-select v-model="editForm.scheduleId" placeholder="選擇班表，留空則視為請假" clearable>
            <el-option
              v-for="s in schedules"
              :key="s.id"
              :label="`${s.name} (${s.start} - ${s.end})`"
              :value="s.id"
            />
            <el-option label="-- 請假 / 停止排班 --" :value="null" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitShift" :loading="submitting">確認修改</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, watch, nextTick } from 'vue'
import api from '../api'
import { ElMessage } from 'element-plus'

interface ShiftDay {
  date: string
  is_manual: boolean
  is_leave: boolean
  is_holiday: boolean
  schedule: {
    id: number
    name: string
    start: string
    end: string
  } | null
}

const employees = ref<any[]>([])
const schedules = ref<any[]>([])
const selectedEmployeeId = ref<number | null>(null)
const viewDate = ref(new Date())
const calendarData = ref<Record<string, ShiftDay>>({})
const loading = ref(false)

// 對話框相關
const dialogVisible = ref(false)
const submitting = ref(false)
const editForm = ref({
  date: '',
  scheduleId: null as number | null
})

// 樣板管理相關
const templateDialogVisible = ref(false)
const templateForm = ref({
  name: '',
  job_start: '',
  job_end: ''
})

const fetchEmployees = async () => {
  const { data } = await api.get('/employees')
  employees.value = data
}

const fetchSchedules = async () => {
  const { data } = await api.get('/schedules')
  schedules.value = data
}

const fetchMonthlyData = async () => {
  if (!selectedEmployeeId.value) return
  
  loading.value = true
  const year = viewDate.value.getFullYear()
  const month = viewDate.value.getMonth() + 1
  
  try {
    const { data } = await api.get('/shifts/calendar', {
      params: { employee_id: selectedEmployeeId.value, year, month }
    })
    
    // 轉換為以日期為 key 的 Map 方便日曆渲染
    const dataMap: Record<string, ShiftDay> = {}
    data.forEach((day: ShiftDay) => { dataMap[day.date] = day })
    calendarData.value = dataMap
  } finally {
    loading.value = false
  }
}

const getShift = (dateStr: string) => calendarData.value[dateStr]

const handleDateClick = (day: string) => {
  const shift = getShift(day)
  editForm.value = { date: day, scheduleId: shift?.schedule?.id || null }
  dialogVisible.value = true
}

const submitShift = async () => {
  if (!selectedEmployeeId.value) return
  submitting.value = true
  try {
    await api.post('/shifts/assign', {
      employee_id: selectedEmployeeId.value,
      schedule_id: editForm.value.scheduleId,
      target_date: editForm.value.date
    })
    ElMessage.success('排班已成功儲存')
    dialogVisible.value = false
    fetchMonthlyData()
  } finally {
    submitting.value = false
  }
}

const handleSyncHolidays = async () => {
  try {
    await api.post('/holidays/sync')
    ElMessage.info('已發送更新假日請求，請稍候再重新整理。')
  } catch (err) {}
}

const openTemplateDialog = () => {
  templateForm.value = { name: '', job_start: '08:30', job_end: '17:30' }
  templateDialogVisible.value = true
}

const submitTemplate = async () => {
  if (!templateForm.value.name) return ElMessage.warning('請輸入樣板名稱')
  submitting.value = true
  try {
    await api.post('/schedules', templateForm.value)
    ElMessage.success('班表樣板新增成功')
    templateDialogVisible.value = false
    fetchSchedules()
  } finally {
    submitting.value = false
  }
}

const handleDeleteTemplate = async (id: number) => {
  try {
    await api.delete(`/schedules/${id}`)
    ElMessage.success('樣板已刪除')
    fetchSchedules()
  } catch (err) {}
}

// 監聽日期變化（處理用戶點擊日曆頂部的上一月/下一月）
watch(viewDate, (newVal, oldVal) => {
  if (newVal.getMonth() !== oldVal.getMonth() || newVal.getFullYear() !== newVal.getFullYear()) {
    fetchMonthlyData()
  }
})

onMounted(() => {
  fetchEmployees()
  fetchSchedules()
})
</script>

<style scoped>
.header-actions {
  margin-bottom: 20px;
}
.calendar-cell {
  height: 100%;
  display: flex;
  flex-direction: column;
}
.cell-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
}
.day-number {
  font-size: 14px;
}
.manual-tag {
  zoom: 0.8;
}
.shift-content {
  flex-grow: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  padding-top: 5px;
}
.shift-name {
  color: #409eff;
  font-weight: bold;
  font-size: 13px;
}
.holiday-text {
  color: #909399;
  font-size: 12px;
}
/* 讓日曆格子點擊區域充滿 */
:deep(.el-calendar-table .el-calendar-day) {
  padding: 0;
  height: 80px;
}
.calendar-cell {
  padding: 8px;
  width: 100%;
  height: 100%;
}
</style>