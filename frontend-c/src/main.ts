import { createApp } from 'vue'
import { ElAlert } from 'element-plus/es/components/alert/index'
import { ElButton } from 'element-plus/es/components/button/index'
import { ElContainer, ElHeader, ElMain } from 'element-plus/es/components/container/index'
import { ElDialog } from 'element-plus/es/components/dialog/index'
import { ElFormItem } from 'element-plus/es/components/form/index'
import { ElIcon } from 'element-plus/es/components/icon/index'
import { ElInput } from 'element-plus/es/components/input/index'
import 'element-plus/dist/index.css'
import './styles/tokens.css'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'

const app = createApp(App)

app
  .use(createPinia())
  .use(router)
  .use(ElAlert)
  .use(ElButton)
  .use(ElContainer)
  .use(ElDialog)
  .use(ElFormItem)
  .use(ElHeader)
  .use(ElIcon)
  .use(ElInput)
  .use(ElMain)
  .mount('#app')
