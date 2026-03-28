<template>
  <div class="cards-view">
    <div class="page-header">
      <h2 class="page-title">卡片管理系統</h2>
      <el-button @click="fetchCards" :loading="loading" circle icon="Refresh" type="primary" plain />
    </div>

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
import { ref, onMounted } from 'vue'
import api from '../api'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'

interface Card {
  id: number
  uid: string
  employee_id: number | null
  owner_name: string | null
}

const cards = ref<Card[]>([])
const loading = ref(false)

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
</script>

<style scoped>
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 15px 25px;
  background: linear-gradient(to right, #ffffff, #f0f7ff);
  border-left: 6px solid #409eff;
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
</style>