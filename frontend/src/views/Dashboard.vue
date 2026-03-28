<template>
  <div class="dashboard">
    <div class="welcome-section">
      <h1 class="welcome-title">歡迎使用 CVTA 考勤管理系統</h1>
      <p class="welcome-subtitle">您可以在此處輕鬆管理員工、排班與查看考勤紀錄。</p>
      <el-divider />
    </div>
  </div>
</template>

<script setup lang="ts">
</script>

<style scoped>
.dashboard {
  padding: 40px;
  text-align: center;
}
.welcome-section {
  max-width: 800px;
  margin: 0 auto;
}
.welcome-title {
  font-size: 36px;
  font-weight: 900;
  color: #409eff;
  margin-bottom: 10px;
}
.welcome-subtitle {
  font-size: 18px;
  color: #909399;
  margin-bottom: 30px;
}
</style>
