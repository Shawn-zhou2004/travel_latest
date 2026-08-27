import { createApp } from 'vue'
import { ElContainer, ElHeader, ElMain } from 'element-plus/es/components/container/index'
import { ElDatePicker } from 'element-plus/es/components/date-picker/index'
import { ElDialog } from 'element-plus/es/components/dialog/index'
import { ElDrawer } from 'element-plus/es/components/drawer/index'
import { ElInput } from 'element-plus/es/components/input/index'
import { ElInputNumber } from 'element-plus/es/components/input-number/index'
import { ElOption, ElSelect } from 'element-plus/es/components/select/index'
import { ElProgress } from 'element-plus/es/components/progress/index'
import { ElTable, ElTableColumn } from 'element-plus/es/components/table/index'
import { ElTag } from 'element-plus/es/components/tag/index'
import 'element-plus/dist/index.css'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'

const app = createApp(App)

app
  .use(createPinia())
  .use(router)
  .use(ElContainer)
  .use(ElDatePicker)
  .use(ElDialog)
  .use(ElDrawer)
  .use(ElHeader)
  .use(ElInput)
  .use(ElInputNumber)
  .use(ElMain)
  .use(ElOption)
  .use(ElProgress)
  .use(ElSelect)
  .use(ElTable)
  .use(ElTableColumn)
  .use(ElTag)
  .mount('#app')
