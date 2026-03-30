<template>
  <div class="shifts-view">
    <div class="page-header">
      <h2 class="page-title">員工排班調度系統</h2>
    </div>

    <el-tabs type="border-card">
      <!-- 頁籤一：日曆排班 -->
      <el-tab-pane label="個人排班">
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
              <el-button type="primary" plain :icon="Refresh" @click="fetchMonthlyData" :disabled="!selectedEmployeeId">
                重新整理
              </el-button>
              <el-button type="warning" plain :icon="Calendar" @click="handleSyncHolidays">
                手動更新假日資料
              </el-button>
            </el-form-item>
          </el-form>
        </div>

        <el-calendar v-if="selectedEmployeeId" ref="personalCalendar" v-model="viewDate" v-loading="loading">
          <template #header>
            <div class="custom-calendar-header">
              <span class="current-month">{{ formatHeaderDate(viewDate) }}</span>
              <el-button-group>
                <el-button size="small" @click="handleCalendarNav('prev-month', 'personal')">
                  上個月
                </el-button>
                <el-button size="small" @click="handleCalendarNav('today', 'personal')">今天</el-button>
                <el-button size="small" @click="handleCalendarNav('next-month', 'personal')">
                  下個月
                </el-button>
              </el-button-group>
            </div>
          </template>
          <template #date-cell="{ data }">
            <div class="calendar-cell" @click="handleDateClick(data.day)">
              <div class="cell-header">
                <span class="day-number">{{ data.day.split('-').slice(2).join('') }}</span>
                <el-tag v-if="getShift(data.day)?.is_leave" size="small" type="danger" effect="dark" class="manual-tag">請假</el-tag>
                <el-tag v-else-if="getShift(data.day)?.is_manual" size="small" type="warning" effect="plain" class="manual-tag">手動</el-tag>
              </div>
              <div v-if="getShift(data.day)" class="shift-content">
                <!-- 班別標籤 -->
                <el-tag
                  v-if="getShift(data.day)?.schedule"
                  effect="dark"
                  size="default"
                  class="shift-tag"
                >
                  {{ getShift(data.day)?.schedule?.name }}
                </el-tag>
                <!-- 休假/請假標籤 -->
                <el-tag
                  v-else
                  :type="getShift(data.day)?.is_leave ? 'danger' : 'info'"
                  effect="plain"
                >
                  {{ getShift(data.day)?.is_leave ? '請假/排休' : '休假' }}
                </el-tag>
              </div>
            </div>
          </template>
        </el-calendar>
        <el-empty v-else description="請先選擇員工以管理排班" />
      </el-tab-pane>

      <!-- 頁籤二：總體排班 (批次處理) -->
      <el-tab-pane label="總體排班">
        <el-row :gutter="20">
          <!-- 左側：日曆選擇 -->
          <el-col :span="10">
            <div class="total-calendar-wrapper">
              <el-calendar ref="totalCalendar" v-model="totalViewDate">
                <template #header>
                  <div class="custom-calendar-header mini">
                    <span class="current-month">{{ formatHeaderDate(totalViewDate) }}</span>
                    <el-button-group>
                      <el-button size="small" @click="handleCalendarNav('prev-month', 'total')">
                        上個月
                      </el-button>
                      <el-button size="small" @click="handleCalendarNav('today', 'total')">今天</el-button>
                      <el-button size="small" @click="handleCalendarNav('next-month', 'total')">
                        下個月
                      </el-button>
                    </el-button-group>
                  </div>
                </template>
                <template #date-cell="{ data }">
                  <div class="calendar-day-cell">
                    <div class="day-num">{{ data.day.split('-').slice(2).join('') }}</div>
                    <!-- 假日紅色標籤 (排除六日) -->
                    <el-tag
                      v-if="isSpecialHoliday(data.day)"
                      type="danger"
                      effect="dark"
                      size="small"
                      class="overall-holiday-tag"
                    >
                      {{ holidaysSummary[data.day].description }}
                    </el-tag>
                    <div class="summary-list">
                      <el-tag
                        v-for="(name, idx) in overallSummary[data.day]?.slice(0, 2)"
                        :key="idx"
                        size="default"
                        effect="dark"
                        class="summary-tag"
                      >
                        {{ name }}
                      </el-tag>
                      <div v-if="overallSummary[data.day]?.length > 2" class="summary-more">
                        +{{ overallSummary[data.day].length - 2 }}...
                      </div>
                    </div>
                  </div>
                </template>
              </el-calendar>
            </div>
          </el-col>

          <!-- 右側：當日排班列表 -->
          <el-col :span="14">
            <el-card shadow="never">
              <template #header>
                <div class="card-header" style="display: flex; justify-content: space-between; align-items: center;">
                  <div style="display: flex; align-items: center;">
                    <span style="font-weight: bold; color: var(--el-color-primary);">{{ formatDate(totalViewDate) }} 排班名單</span>
                    <!-- 顯示當日假日詳細資訊 -->
                    <el-tooltip
                      v-if="holidaysSummary[formatDate(totalViewDate)] && !holidaysSummary[formatDate(totalViewDate)].is_workday"
                      :content="holidaysSummary[formatDate(totalViewDate)].description"
                      placement="top"
                      :disabled="holidaysSummary[formatDate(totalViewDate)].description.length < 10"
                    >
                      <el-tag
                        type="danger"
                        size="small"
                        effect="dark"
                        style="margin-left: 10px; cursor: help;"
                      >
                        {{ holidaysSummary[formatDate(totalViewDate)].description }}
                      </el-tag>
                    </el-tooltip>
                  </div>
                  <div style="display: flex; gap: 10px; align-items: center;">
                    <el-button 
                      :type="isCurrentDateHoliday ? 'info' : 'danger'" 
                      size="small" 
                      @click="handleToggleHoliday" 
                      :loading="submitting" 
                      plain
                    >
                      {{ isCurrentDateHoliday ? '移除假日' : '設為假日' }}
                    </el-button>
                    <el-select 
                      v-model="addEmpId" 
                      placeholder="新增人員..." 
                      filterable 
                      @change="addEmployeeToBatchList"
                      style="width: 150px"
                    >
                      <el-option
                        v-for="e in employees"
                        :key="e.id"
                        :label="e.name"
                        :value="e.id"
                        :disabled="isEmployeeInBatchList(e.id)"
                      />
                    </el-select>
                  </div>
                </div>
              </template>

              <el-table :data="dayAssignments" border stripe max-height="650">
                <el-table-column prop="employee_name" label="員工姓名" width="120" />
                <el-table-column label="預計班別">
                  <template #default="scope">
                    <el-select v-model="scope.row.schedule_id" placeholder="預設班別" clearable style="width: 100%">
                      <el-option
                        v-for="s in schedules"
                        :key="s.id"
                        :label="`${s.name} (${s.start}-${s.end})`"
                        :value="s.id"
                      />
                    </el-select>
                  </template>
                </el-table-column>
                <el-table-column label="操作" width="70" align="center">
                  <template #default="scope">
                    <el-button type="danger" icon="Delete" circle size="small" @click="removeEmployeeFromBatchList(scope.$index)" />
                  </template>
                </el-table-column>
              </el-table>

              <div style="margin-top: 20px; text-align: right;">
                <el-button @click="fetchDaySummary">取消並重設</el-button>
                <el-button type="primary" :loading="submitting" @click="submitBatchShift">
                  更新 {{ formatDate(totalViewDate) }} 排班
                </el-button>
              </div>
            </el-card>
          </el-col>
        </el-row>
      </el-tab-pane>

      <!-- 頁籤二：班表樣板管理 -->
      <el-tab-pane label="樣板管理">
        <div class="header-actions">
          <el-button type="primary" :icon="Plus" @click="openTemplateDialog">新增班表樣板</el-button>
        </div>
        <el-table :data="schedules" border style="margin-top: 20px">
          <el-table-column prop="name" label="班表名稱" />
          <el-table-column prop="start" label="上班時間" />
          <el-table-column prop="end" label="下班時間" />
          <el-table-column label="操作" width="120">
            <template #default="scope">
              <el-popconfirm title="確定要刪除此樣板嗎？" @confirm="handleDeleteTemplate(scope.row.id)">
                <template #reference>
                  <el-button type="danger" size="small" :icon="Delete" circle />
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

    <!-- 假日同步預覽對話框 -->
    <el-dialog
      v-model="syncDialogVisible"
      title="政府假日同步預覽"
      width="600px"
      :close-on-click-modal="false"
    >
      <div style="margin-bottom: 15px; color: #666; font-size: 14px;">
        請勾選欲匯入系統的假日資料。預設已過濾掉標準週休二日。
      </div>
      <el-table
        ref="holidayTableRef"
        :data="candidates"
        v-loading="syncLoading"
        max-height="500"
        @selection-change="handleSelectionChange"
      >
        <el-table-column type="selection" width="55" />
        <el-table-column prop="date" label="日期" width="120" />
        <el-table-column prop="description" label="名稱/描述" />
        <template #empty>
          <span>無可更新的假日資料</span>
        </template>
      </el-table>
      <template #footer>
        <el-button @click="syncDialogVisible = false">取消</el-button>
        <el-button 
          type="primary" 
          @click="submitHolidays" 
          :loading="submitting"
          :disabled="selectedHolidays.length === 0"
        >
          確認匯入 ({{ selectedHolidays.length }} 筆)
        </el-button>
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
import { ref, onMounted, watch, nextTick, computed } from 'vue'
import api from '../api'
import { ElMessage } from 'element-plus'
import { Refresh, Calendar, Plus, Delete} from '@element-plus/icons-vue'

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

// 總體排班相關
const totalViewDate = ref(new Date())
const dayAssignments = ref<any[]>([])
const addEmpId = ref<number | null>(null)
const personalCalendar = ref<any>(null)
const totalCalendar = ref<any>(null)

const formatHeaderDate = (date: Date) => {
  return `${date.getFullYear()} 年 ${String(date.getMonth() + 1).padStart(2, '0')} 月`
}

const handleCalendarNav = (type: 'prev-month' | 'next-month' | 'today', target: 'personal' | 'total') => {
  const calendar = target === 'personal' ? personalCalendar.value : totalCalendar.value
  calendar?.selectDate(type)
}

const overallSummary = ref<Record<string, string[]>>({})
const holidaysSummary = ref<Record<string, { description: string, is_workday: boolean }>>({})

const formatDate = (d: Date) => {
  const year = d.getFullYear()
  const month = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

// 假日同步相關
const syncDialogVisible = ref(false)
const syncLoading = ref(false)
const candidates = ref<any[]>([])
const selectedHolidays = ref<any[]>([])
const holidayTableRef = ref<any>(null)

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
  if (submitting.value) return // 邏輯鎖：防止連續點擊
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

const fetchDaySummary = async () => {
  const dateStr = formatDate(totalViewDate.value)
  try {
    const { data } = await api.get('/shifts/day-summary', { params: { target_date: dateStr } })
    dayAssignments.value = data
  } catch (err) {}
}

const fetchOverallSummary = async () => {
  const year = totalViewDate.value.getFullYear()
  const month = totalViewDate.value.getMonth() + 1
  try {
    // 同時獲取排班摘要與假日資料
    const [summaryRes, holidayRes] = await Promise.all([
      api.get('/shifts/monthly-summary', { params: { year, month } }),
      api.get('/holidays/monthly', { params: { year, month } })
    ])
    overallSummary.value = summaryRes.data
    holidaysSummary.value = holidayRes.data
  } catch (err) {}
}

const isSpecialHoliday = (day: string) => {
  const h = holidaysSummary.value[day]
  if (!h || h.is_workday) return false
  
  // 檢查是否為平日 (週一至週五)
  const [y, m, d] = day.split('-').map(Number)
  const dt = new Date(y, m - 1, d)
  const dayOfWeek = dt.getDay() // 0 是週日, 6 是週六
  return dayOfWeek !== 0 && dayOfWeek !== 6
}

const isCurrentDateHoliday = computed(() => {
  const dateStr = formatDate(totalViewDate.value)
  const h = holidaysSummary.value[dateStr]
  return h && !h.is_workday
})

const handleToggleHoliday = async () => {
  if (submitting.value) return // 邏輯鎖：防止連續點擊
  const dateStr = formatDate(totalViewDate.value)
  const isHoliday = isCurrentDateHoliday.value
  submitting.value = true
  try {
    await api.post('/holidays/apply', {
      holidays: [{
        date: dateStr,
        is_workday: isHoliday, // 如果現在是假日(false)，則設為工作日(true)來移除；反之亦然
        description: isHoliday ? '' : '休假'
      }]
    })
    ElMessage.success(`${dateStr} ${isHoliday ? '已移除假日設定' : '已成功設定為假日'}`)
    fetchOverallSummary() // 重新整理日曆標記
  } catch (err) {}
  finally {
    submitting.value = false
  }
}

const addEmployeeToBatchList = (empId: number) => {
  const emp = employees.value.find(e => e.id === empId)
  if (emp) {
    dayAssignments.value.push({
      employee_id: emp.id,
      employee_name: emp.name,
      schedule_id: emp.schedule_id // 預設帶入該員工的平常班別
    })
  }
  addEmpId.value = null
}

const isEmployeeInBatchList = (empId: number) => {
  return dayAssignments.value.some(a => a.employee_id === empId)
}

const removeEmployeeFromBatchList = (index: number) => {
  dayAssignments.value.splice(index, 1)
}

const submitBatchShift = async () => {
  if (submitting.value) return // 邏輯鎖
  submitting.value = true
  try {
    await api.post('/shifts/batch-assign', {
      target_date: formatDate(totalViewDate.value),
      assignments: dayAssignments.value.map(a => ({
        employee_id: a.employee_id,
        schedule_id: a.schedule_id
      }))
    })
    ElMessage.success('總體排班更新成功')
    fetchMonthlyData() // 同步更新個人日曆視圖
    fetchOverallSummary() // 更新總體摘要
  } finally {
    submitting.value = false
  }
}

// 監聽總體排班日曆日期變化
watch(totalViewDate, (newVal, oldVal) => {
  fetchDaySummary()
  if (syncLoading.value) return
  // 如果月份有變，重新抓取整月摘要
  if (!oldVal || newVal.getMonth() !== oldVal.getMonth() || newVal.getFullYear() !== oldVal.getFullYear()) {
    fetchOverallSummary()
  }
})

const handleSyncHolidays = async () => {
  syncDialogVisible.value = true
  syncLoading.value = true
  candidates.value = []
  
  try {
    const { data } = await api.get('/holidays/candidates')
    candidates.value = data
    
    // 預設全選
    await nextTick()
    if (holidayTableRef.value) {
      candidates.value.forEach(row => {
        holidayTableRef.value.toggleRowSelection(row, true)
      })
    }
  } finally {
    syncLoading.value = false
  }
}

const handleSelectionChange = (val: any[]) => {
  selectedHolidays.value = val
}

const submitHolidays = async () => {
  if (submitting.value) return
  submitting.value = true
  try {
    await api.post('/holidays/apply', { holidays: selectedHolidays.value })
    ElMessage.success('假日資料已成功更新')
    syncDialogVisible.value = false
    fetchMonthlyData()
  } finally {
    submitting.value = false
  }
}

const openTemplateDialog = () => {
  templateForm.value = { name: '', job_start: '08:30', job_end: '17:30' }
  templateDialogVisible.value = true
}

const submitTemplate = async () => {
  if (!templateForm.value.name) return ElMessage.warning('請輸入樣板名稱')
  if (submitting.value) return
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
  if (newVal.getMonth() !== oldVal.getMonth() || newVal.getFullYear() !== oldVal.getFullYear()) {
    fetchMonthlyData()
  }
})

onMounted(() => {
  fetchEmployees()
  fetchSchedules()
  fetchOverallSummary()
})
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
.shift-tag {
  width: 85%;
  font-weight: bold;
  font-size: 14px;
  height: 32px;
  border-radius: 6px;
}
.holiday-text {
  color: var(--el-color-danger);
  font-size: 12px;
}
/* 讓日曆格子點擊區域充滿 */
:deep(.el-calendar-table .el-calendar-day) {
  padding: 0;
  height: 110px;
}
.calendar-cell {
  padding: 8px;
  width: 100%;
  height: 100%;
}
.calendar-day-cell {
  display: flex;
  flex-direction: column;
  align-items: center;
  height: 100%;
}
.summary-list {
  margin-top: 4px;
  display: flex;
  flex-direction: column;
  gap: 2px;
  align-items: center;
  width: 100%;
}
.summary-tag {
  max-width: 90%;
  border-radius: 4px;
  font-weight: bold;
  margin-bottom: 2px;
  font-size: 14px;
  height: 28px;
}
.summary-more {
  font-size: 12px;
  color: #909399;
  font-style: italic;
  margin-top: 2px;
}
.overall-holiday-tag {
  margin-bottom: 4px;
  font-size: 12px;
  max-width: 95%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.custom-calendar-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 20px;
  background: linear-gradient(to right, #3F4E4F, #2C3639);
  border-left: 5px solid #A27B5C;
  margin-bottom: 15px;
  border-radius: 4px;
  box-shadow: 0 2px 4px rgba(0,0,0,0.05);
}
.current-month {
  font-size: 22px;
  font-weight: 800;
  color: #DCD7C9;
  letter-spacing: 1px;
}
.custom-calendar-header.mini {
  padding: 8px 15px;
}
.custom-calendar-header.mini .current-month {
  font-size: 18px;
}
</style>