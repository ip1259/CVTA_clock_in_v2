<template>
  <el-container class="layout-container">
    <el-aside width="200px">
      <el-menu :router="true" :default-active="$route.path" class="el-menu-vertical">
        <el-menu-item index="/">儀表板</el-menu-item>
        <el-menu-item index="/personnel">人事管理</el-menu-item>
        <el-menu-item index="/cards">卡片管理</el-menu-item>
        <el-menu-item index="/shifts">排班管理</el-menu-item>
        <el-menu-item index="/records">考勤報表</el-menu-item>
        <el-menu-item index="/system">系統管理</el-menu-item>
        <el-divider />
        <el-menu-item @click="handleLogout">登出</el-menu-item>
      </el-menu>
    </el-aside>
    <el-container>
      <el-header class="header">
        <span>CVTA 後台管理介面</span>
      </el-header>
      <el-main>
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup lang="ts">
import { useRouter } from 'vue-router'
import { ElMessageBox } from 'element-plus'

const router = useRouter()

const handleLogout = () => {
  ElMessageBox.confirm('確定要登出系統嗎？', '提示', { type: 'warning' }).then(() => {
    localStorage.removeItem('token')
    router.push('/login')
  })
}
</script>

<style scoped>
.layout-container {
  height: 100vh;
}
.el-menu-vertical {
  height: 100%;
}
.header {
  background-color: #fff;
  color: #333;
  line-height: 60px;
  border-bottom: 1px solid #dcdfe6;
  text-align: right;
  font-weight: bold;
}
</style>
