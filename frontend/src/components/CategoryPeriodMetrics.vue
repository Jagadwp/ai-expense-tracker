<script setup lang="ts">
import type { CategoryPeriodComparison } from '../types'

defineProps<{ comparisons: CategoryPeriodComparison[] }>()

function delta(c: CategoryPeriodComparison): number {
  return c.current_total - c.previous_total
}

function deltaPct(c: CategoryPeriodComparison): number | null {
  if (c.previous_total === 0) return null
  return (delta(c) / c.previous_total) * 100
}

function formatRp(value: number): string {
  return `Rp ${Math.round(value).toLocaleString('id-ID')}`
}
</script>

<template>
  <div class="section">
    <h3>Spend by category — period vs. previous</h3>
    <p v-if="!comparisons.length" class="empty">No data for the selected period.</p>
    <div v-else class="grid">
      <div v-for="c in comparisons" :key="c.category" class="metric-card">
        <span class="label">{{ c.category }}</span>
        <span class="value">{{ formatRp(c.current_total) }}</span>
        <span class="previous">was {{ formatRp(c.previous_total) }}</span>
        <span class="change" :class="{ negative: delta(c) < 0, positive: delta(c) > 0 }">
          {{ formatRp(delta(c)) }}
          <template v-if="deltaPct(c) !== null">({{ deltaPct(c)! >= 0 ? '+' : '' }}{{ deltaPct(c)!.toFixed(1) }}%)</template>
        </span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.section {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  box-shadow: var(--shadow);
  padding: 1.5rem;
}

h3 {
  margin: 0 0 1rem;
  font-size: 1rem;
}

.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 1rem;
}

.metric-card {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  padding: 1rem;
  border: 1px solid var(--border);
  border-radius: 10px;
}

.label {
  font-size: 0.8rem;
  color: var(--text-secondary);
  text-transform: capitalize;
}

.value {
  font-size: 1.25rem;
  font-weight: 600;
}

.previous {
  font-size: 0.75rem;
  color: var(--text-secondary);
}

.change {
  font-size: 0.8rem;
  font-weight: 500;
}

.change.negative {
  color: var(--success);
}

.change.positive {
  color: var(--danger);
}

.empty {
  color: var(--text-secondary);
  font-size: 0.9rem;
}
</style>
