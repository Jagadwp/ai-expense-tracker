<script setup lang="ts">
import { computed } from 'vue'
import { Doughnut } from 'vue-chartjs'
import type { CategoryTotal } from '../types'

const props = defineProps<{ totals: CategoryTotal[] }>()

const palette = ['#4f46e5', '#0ea5e9', '#f472b6', '#f59e0b', '#10b981', '#a78bfa', '#f87171']

const chartData = computed(() => ({
  labels: props.totals.map((t) => t.category),
  datasets: [
    {
      data: props.totals.map((t) => t.total),
      backgroundColor: props.totals.map((_, i) => palette[i % palette.length]),
      borderWidth: 0,
    },
  ],
}))

const chartOptions = {
  plugins: {
    legend: { position: 'right' as const, labels: { color: '#374151', boxWidth: 12, font: { size: 12 } } },
  },
}
</script>

<template>
  <div class="chart-card">
    <h3>Spend by category</h3>
    <Doughnut v-if="totals.length" :data="chartData" :options="chartOptions" />
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
