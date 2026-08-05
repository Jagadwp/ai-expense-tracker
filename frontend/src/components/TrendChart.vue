<script setup lang="ts">
import { computed } from 'vue'
import { Line } from 'vue-chartjs'
import type { TrendPoint } from '../types'

const props = defineProps<{ trend: TrendPoint[] }>()

const chartData = computed(() => ({
  labels: props.trend.map((t) => t.date),
  datasets: [
    {
      label: 'total',
      data: props.trend.map((t) => t.total),
      borderColor: '#4f46e5',
      backgroundColor: 'rgba(79, 70, 229, 0.08)',
      fill: true,
      tension: 0.3,
      pointRadius: 2,
    },
  ],
}))

const chartOptions = {
  scales: {
    x: { ticks: { color: '#6b7280', font: { size: 11 } }, grid: { display: false } },
    y: { ticks: { color: '#6b7280', font: { size: 11 } }, grid: { color: '#f1f5f9' } },
  },
  plugins: {
    legend: { display: false },
  },
}
</script>

<template>
  <div class="chart-card">
    <h3>Spend trend</h3>
    <Line v-if="trend.length" :data="chartData" :options="chartOptions" />
    <p v-else class="empty">No data for the selected period.</p>
  </div>
</template>

<style scoped>
.chart-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  box-shadow: var(--shadow);
  padding: 1.5rem;
  min-height: 320px;
}

h3 {
  margin: 0 0 1rem;
  font-size: 1rem;
  color: var(--text-primary);
}

.empty {
  color: var(--text-secondary);
  font-size: 0.9rem;
}
</style>
