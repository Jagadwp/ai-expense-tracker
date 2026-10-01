<script setup lang="ts">
import { computed } from 'vue'
import { Doughnut } from 'vue-chartjs'
import type { CategoryTotal } from '../types'

// embedded: used when a parent already provides its own card box/heading
// (see App.vue's mobile chart toggle) — skips this component's own title
// and outer card styling so it doesn't nest inside another card.
const props = defineProps<{ totals: CategoryTotal[]; embedded?: boolean }>()

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

const total = computed(() => props.totals.reduce((sum, t) => sum + t.total, 0))

function percentOf(value: number): string {
  return total.value ? `${Math.round((value / total.value) * 1000) / 10}%` : '0%'
}

function formatRp(value: number): string {
  return `Rp ${Math.round(value).toLocaleString('id-ID')}`
}

// `any` here matches vue-chartjs/Chart.js's own loosely-typed plugin
// callback signatures — typing them precisely fights the library more than
// it helps, and these callbacks only ever read .dataIndex off the args.
const chartOptions = computed(() => ({
  plugins: {
    legend: {
      position: 'right' as const,
      labels: {
        color: '#374151',
        boxWidth: 12,
        font: { size: 12 },
        generateLabels: () =>
          props.totals.map((t, i) => ({
            text: `${t.category} (${percentOf(t.total)})`,
            fillStyle: palette[i % palette.length],
            strokeStyle: palette[i % palette.length],
            index: i,
          })),
      },
    },
    tooltip: {
      callbacks: {
        label: (ctx: any) => {
          const t = props.totals[ctx.dataIndex]
          return `${t.category}: ${formatRp(t.total)} (${percentOf(t.total)})`
        },
      },
    },
  },
}))
</script>

<template>
  <div :class="{ 'chart-card': !embedded }">
    <h3 v-if="!embedded">Spend by category</h3>
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
