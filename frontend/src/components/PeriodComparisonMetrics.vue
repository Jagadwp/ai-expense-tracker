<script setup lang="ts">
import { computed } from 'vue'
import type { PeriodComparison } from '../types'

const props = defineProps<{ comparison: PeriodComparison; dateFrom: string; dateTo: string }>()

const delta = computed(() => props.comparison.current_total - props.comparison.previous_total)
const deltaPct = computed(() => {
  if (props.comparison.previous_total === 0) return null
  return (delta.value / props.comparison.previous_total) * 100
})

// Both periods span the same number of days (previous_total is the
// immediately preceding period of the same length — see
// store.period_comparison()), so one day count applies to both averages.
const days = computed(() => {
  const from = new Date(props.dateFrom)
  const to = new Date(props.dateTo)
  return Math.max(1, Math.round((to.getTime() - from.getTime()) / 86_400_000) + 1)
})
const avgCurrent = computed(() => props.comparison.current_total / days.value)
const avgPrevious = computed(() => props.comparison.previous_total / days.value)

function formatRp(value: number): string {
  return `Rp ${Math.round(value).toLocaleString('id-ID')}`
}
</script>

<template>
  <div class="metrics">
    <div class="metric-card">
      <span class="label">Selected period</span>
      <span class="value">{{ formatRp(comparison.current_total) }}</span>
      <span class="avg">avg {{ formatRp(avgCurrent) }}/day</span>
    </div>
    <div class="metric-card desktop-only">
      <span class="label">Previous period</span>
      <span class="value">{{ formatRp(comparison.previous_total) }}</span>
      <span class="avg">avg {{ formatRp(avgPrevious) }}/day</span>
    </div>
    <div class="metric-card">
      <span class="label">Change</span>
      <span class="value" :class="{ negative: delta < 0, positive: delta > 0 }">
        {{ formatRp(delta) }}
        <span v-if="deltaPct !== null" class="pct">({{ deltaPct >= 0 ? '+' : '' }}{{ deltaPct.toFixed(1) }}%)</span>
      </span>
    </div>
  </div>
</template>

<style scoped>
.metrics {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 1rem;
}

.metric-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  box-shadow: var(--shadow);
  padding: 1.25rem 1.5rem;
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
}

.label {
  font-size: 0.85rem;
  color: var(--text-secondary);
}

.value {
  font-size: 1.6rem;
  font-weight: 600;
}

.pct {
  font-size: 0.9rem;
  font-weight: 500;
}

.avg {
  font-size: 0.8rem;
  color: var(--text-secondary);
  font-weight: 500;
}

.value.negative {
  color: var(--success);
}

.value.positive {
  color: var(--danger);
}

@media (max-width: 600px) {
  .metrics {
    grid-template-columns: 1fr;
  }

  /* Scoped styles from a parent don't reach elements nested inside this
     component's own template (only its root) — this rule has to live
     here, not in App.vue, even though App.vue is what decides which
     sections are desktop-only. */
  .desktop-only {
    display: none;
  }
}
</style>
