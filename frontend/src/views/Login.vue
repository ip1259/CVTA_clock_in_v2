<template>
  <div class="login-page">
    <el-card class="login-card">
      <template #header>
        <div class="card-header">
          <span>CVTA 考勤管理系統</span>
        </div>
      </template>
      <el-form :model="loginForm" @keyup.enter="handleLogin">
        <el-form-item label="帳號">
          <el-input v-model="loginForm.username" placeholder="請輸入管理員帳號" />
        </el-form-item>
        <el-form-item label="密碼">
          <el-input 
            v-model="loginForm.password" 
            type="password" 
            placeholder="請輸入密碼" 
            show-password 
          />
        </el-form-item>
        <el-form-item>
          <el-button 
            type="primary" 
            :loading="loading" 
            @click="handleLogin" 
            style="width: 100%"
          >
            登入
          </el-button>
        </el-form-item>
      </el-form>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import api from '../api'
import { ElMessage } from 'element-plus'

const router = useRouter()
const loading = ref(false)
const loginForm = ref({
  username: '',
  password: ''
})

const handleLogin = async () => {
  if (!loginForm.value.username || !loginForm.value.password) {
    ElMessage.warning('請輸入帳號與密碼')
    return
  }

  loading.value = true
  try {
    const response = await api.post('/login', loginForm.value)
    const { access_token } = response.data
    localStorage.setItem('token', access_token)
    ElMessage.success('登入成功')
    router.push('/')
  } catch (error) {
    // 錯誤訊息已由 api/index.ts 的攔截器處理
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-page {
  display: flex;
  justify-content: center;
  align-items: center;
  height: 100vh;
  background-color: #f5f7fa;
}
.login-card {
  width: 400px;
}
.card-header {
  text-align: center;
  font-weight: bold;
  font-size: 1.2rem;
}
</style>
