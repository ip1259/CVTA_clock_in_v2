<template>
  <div class="dashboard">
    <!-- 頂部統計卡片 -->
    <el-row :gutter="20">
      <el-col :span="6" v-for="(item, index) in statCards" :key="index">
        <el-card shadow="hover" class="stat-card" :class="item.type">
          <div class="stat-content">
            <el-icon class="stat-icon"><component :is="item.icon" /></el-icon>
            <div class="stat-info">
              <div class="stat-label">{{ item.label }}</div>
              <div class="stat-value">{{ item.value }}</div>
            </div>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="20" style="margin-top: 25px">
      <!-- 左側：即時動態 -->
      <el-col :span="16">
        <el-card header="最新打卡動態" shadow="never">
          <el-timeline v-if="activities.length > 0">
            <el-timeline-item
              v-for="(act, idx) in activities"
              :key="idx"
              :timestamp="act.time"
              :type="act.note.includes('[手動]') ? 'warning' : 'primary'"
            >
              <span class="activity-name">{{ act.name }}</span>
              <el-tag size="small" effect="plain" style="margin-left: 10px">{{ act.note }}</el-tag>
            </el-timeline-item>
          </el-timeline>
          <el-empty v-else description="今日尚無打卡紀錄" :image-size="100" />
        </el-card>
      </el-col>

      <!-- 右側：快捷功能與系統狀態 -->
      <el-col :span="8">
        <el-card header="系統便捷入口" shadow="never">
          <div class="quick-actions">
            <el-button @click="$router.push('/personnel')" icon="User" class="action-btn">人事管理</el-button>
            <el-button @click="$router.push('/records')" icon="Document" class="action-btn">匯出報表</el-button>
            <el-button @click="$router.push('/shifts')" icon="Calendar" class="action-btn">調整排班</el-button>
          </div>
          <el-divider />
          <div class="system-status">
            <div class="status-item">
              <span>資料庫狀態</span>
              <el-tag size="small" type="success">連線正常</el-tag>
            </div>
            <div class="status-item">
              <span>讀卡端伺服器</span>
              <el-tag size="small" type="success">運行中</el-tag>
            </div>
          </div>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import api from '../api'
import { User, CreditCard, Pointer, Checked } from '@element-plus/icons-vue'

const stats = ref({
  total_employees: 0,
  active_employees: 0,
  unassigned_cards: 0,
  today_punches: 0
})
const activities = ref<any[]>([])

const statCards = computed(() => [
  { label: '在職總人數', value: stats.value.active_employees, icon: User, type: 'primary' },
  { label: '今日打卡次數', value: stats.value.today_punches, icon: Pointer, type: 'success' },
  { label: '待處理空卡', value: stats.value.unassigned_cards, icon: CreditCard, type: 'warning' },
  { label: '系統總人數', value: stats.value.total_employees, icon: Checked, type: 'info' }
])

const fetchDashboardData = async () => {
  try {
    const { data } = await api.get('/dashboard/summary')
    stats.value = data.stats
    activities.value = data.activities
  } catch (err) {}
}

onMounted(fetchDashboardData)
</script>

<style scoped>
.dashboard {
  padding: 10px;
}
.stat-card {
  border-radius: 12px;
  border: none;
  color: white;
}
.stat-card.primary { background: linear-gradient(135deg, #A27B5C 0%, #3F4E4F 100%); }
.stat-card.success { background: linear-gradient(135deg, #3F4E4F 0%, #2C3639 100%); }
.stat-card.warning { background: linear-gradient(135deg, #A27B5C 0%, #2C3639 100%); }
.stat-card.info { background: linear-gradient(135deg, #3F4E4F 0%, #A27B5C 100%); }

.stat-content {
  display: flex;
  align-items: center;
}
.stat-icon {
  font-size: 40px;
  opacity: 0.3;
  margin-right: 15px;
}
.stat-label {
  font-size: 14px;
  opacity: 0.9;
}
.stat-value {
  font-size: 28px;
  font-weight: bold;
}
.activity-name {
  font-weight: bold;
  color: var(--el-text-color-primary);
}
.quick-actions {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.action-btn {
  width: 100%;
  justify-content: flex-start;
}
.status-item {
  display: flex;
  justify-content: space-between;
  margin-bottom: 10px;
  font-size: 14px;
  color: #606266;
}
</style>
