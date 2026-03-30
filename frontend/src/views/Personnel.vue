<template>
  <div class="personnel-view">
    <div class="page-header">
      <h2 class="page-title">人事資料管理</h2>
    </div>

    <div class="header-actions">
      <el-button type="primary" @click="openAddDialog">新增員工</el-button>
      <el-checkbox v-model="filterActive" @change="fetchEmployees" style="margin-left: 20px">
        僅顯示在職人員
      </el-checkbox>
    </div>

    <el-table :data="employees" v-loading="loading" style="width: 100%; margin-top: 20px" border>
      <el-table-column prop="id" label="ID" width="80" />
      <el-table-column prop="name" label="姓名" />
      <el-table-column prop="nickname" label="暱稱" />
      <el-table-column label="預設班表">
        <template #default="scope">
          <el-tag v-if="getScheduleName(scope.row.schedule_id)" type="info">
            {{ getScheduleName(scope.row.schedule_id) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="在職狀態" width="120">
        <template #default="scope">
          <el-switch
            v-model="scope.row.is_active"
            @change="(val: boolean) => handleStatusChange(scope.row, val)"
          />
        </template>
      </el-table-column>
      <el-table-column label="操作" width="150">
        <template #default="scope">
          <el-button size="small" @click="editEmployee(scope.row)">編輯</el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- 新增員工對話框 -->
    <el-dialog v-model="dialogVisible" :title="isEdit ? '編輯員工' : '新增員工'" width="500px">
      <el-form :model="form" label-width="100px">
        <el-form-item label="姓名" required>
          <el-input v-model="form.name" />
        </el-form-item>
        <el-form-item label="暱稱">
          <el-input v-model="form.nickname" />
        </el-form-item>
        <el-form-item label="預設班表">
          <el-select v-model="form.schedule_id" placeholder="選擇固定班表樣板" clearable>
            <el-option
              v-for="s in schedules"
              :key="s.id"
              :label="`${s.name} (${s.start}-${s.end})`"
              :value="s.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="綁定卡片">
          <el-select v-model="form.selectedCard" placeholder="選擇未分配的卡片" clearable>
            <el-option
              v-for="card in unassignedCards"
              :key="card.uid"
              :label="card.uid"
              :value="card.uid"
            />
          </el-select>
          <el-button link type="primary" @click="fetchUnassignedCards" style="margin-left: 10px">
            重新整理卡片
          </el-button>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="handleSubmit" :loading="submitting">確定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import api from '../api'
import { ElMessage } from 'element-plus'

interface Employee {
  id: number
  name: string
  nickname: string
  is_active: boolean
  schedule_id: number | null
}

interface Card {
  id: number
  uid: string
}

const employees = ref<Employee[]>([])
const unassignedCards = ref<Card[]>([])
const schedules = ref<any[]>([])
const loading = ref(false)
const filterActive = ref(true)
const isEdit = ref(false)
const editingId = ref<number | null>(null)

// 表單相關
const dialogVisible = ref(false)
const submitting = ref(false)
const form = ref({
  name: '',
  nickname: '',
  schedule_id: null as number | null,
  selectedCard: ''
})

// 獲取班表列表
const fetchSchedules = async () => {
  const { data } = await api.get('/schedules')
  schedules.value = data
}

const getScheduleName = (id: number | null) => {
  const s = schedules.value.find(item => item.id === id)
  return s ? s.name : ''
}

// 獲取員工清單
const fetchEmployees = async () => {
  loading.value = true
  try {
    const { data } = await api.get('/employees', {
      params: { active_only: filterActive.value }
    })
    employees.value = data
  } finally {
    loading.value = false
  }
}

// 獲取未分配卡片
const fetchUnassignedCards = async () => {
  const { data } = await api.get('/cards/unassigned')
  unassignedCards.value = data
}

// 切換在職狀態
const handleStatusChange = async (row: Employee, val: any) => {
  try {
    await api.put(`/employees/${row.id}/status`, null, {
      params: { is_active: val }
    })
    ElMessage.success(`員工 ${row.name} 狀態已更新`)
  } catch {
    row.is_active = !val // 失敗時回滾 UI 狀態
  }
}

const openAddDialog = () => {
  isEdit.value = false
  editingId.value = null
  form.value = { name: '', nickname: '', schedule_id: null, selectedCard: '' }
  fetchUnassignedCards()
  dialogVisible.value = true
}

const handleSubmit = async () => {
  if (!form.value.name) return ElMessage.warning('請輸入姓名')
  
  submitting.value = true
  try {
    if (isEdit.value && editingId.value) {
      // 編輯模式
      await api.put(`/employees/${editingId.value}`, {
        name: form.value.name,
        nickname: form.value.nickname,
        schedule_id: form.value.schedule_id
      })
      // 如果有選取新卡片，追加綁定
      if (form.value.selectedCard) {
        await api.post('/employees/bind-card', {
          employee_id: editingId.value,
          uid: form.value.selectedCard
        })
      }
      ElMessage.success('更新成功')
    } else {
      // 新增模式
      await api.post('/employees', {
        name: form.value.name,
        nickname: form.value.nickname,
        schedule_id: form.value.schedule_id,
        card_uids: form.value.selectedCard ? [form.value.selectedCard] : []
      })
      ElMessage.success('新增成功')
    }
    dialogVisible.value = false
    fetchEmployees()
  } finally {
    submitting.value = false
  }
}

const editEmployee = (row: Employee) => {
  isEdit.value = true
  editingId.value = row.id
  form.value = {
    name: row.name,
    nickname: row.nickname,
    schedule_id: row.schedule_id,
    selectedCard: '' // 預設不變動卡片
  }
  fetchUnassignedCards()
  dialogVisible.value = true
}

onMounted(() => {
  fetchSchedules()
  fetchEmployees()
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
  letter-spacing: 1px;
}

.header-actions {
  display: flex;
  align-items: center;
  margin-bottom: 20px;
}
</style>