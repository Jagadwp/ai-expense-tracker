<script setup lang="ts">
import { computed } from 'vue'
import { Line } from 'vue-chartjs'
import type { CategoryTrendPoint } from '../types'

const props = defineProps<{ trend: CategoryTrendPoint[] }>()

const palette = ['#4f46e5', '#0ea5e9', '#f472b6', '#f59e0b', '#10b981', '#a78bfa', '#f87171']

const dates = computed(() => Array.from(new Set(props.trend.map((p) => p.date))).sort())

const categories = computed(() => Array.from(new Set(props.trend.map((p) => p.category))).sort())

const chartData = computed(() => {
  const byCategory = new Map<string, Map<string, number>>()
  for (const point of props.trend) {
    if (!byCategory.has(point.category)) byCategory.set(point.category, new Map())
    byCategory.get(point.category)!.set(point.date, point.total)
  }

  return {
    labels: dates.value,
    datasets: categories.value.map((category, i) => ({
      label: category,
      data: dates.value.map((d) => byCategory.get(category)?.get(d) ?? 0),
      borderColor: palette[i % palette.length],
      backgroundColor: palette[i % palette.length],
      tension: 0.3,
      pointRadius: 1.5,
    })),
  }
})

const chartOptions = {
  scales: {
    x: { ticks: { color: '#6b7280', font: { size: 11 } }, grid: { display: false } },
    y: { ticks: { color: '#6b7280', font: { size: 11 } }, grid: { color: '#f1f5f9' } },
  },
  plugins: {
    legend: { position: 'bottom' as const, labels: { color: '#374151', boxWidth: 12, font: { size: 12 } } },
  },
}
</script>

<template>
  <div class="chart-card">
    <h3>Spend trend by category</h3>
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
  min-height: 360px;
}

h3 {
  margin: 0 0 1rem;
  font-size: 1rem;
}

.empty {
  color: var(--text-secondary);
  font-size: 0.9rem;
}
</style>
