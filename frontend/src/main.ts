import { createApp } from 'vue'
import { Chart as ChartJS, ArcElement, CategoryScale, LinearScale, LineElement, PointElement, Tooltip, Legend } from 'chart.js'
import './style.css'
import App from './App.vue'

ChartJS.register(ArcElement, CategoryScale, LinearScale, LineElement, PointElement, Tooltip, Legend)

createApp(App).mount('#app')
