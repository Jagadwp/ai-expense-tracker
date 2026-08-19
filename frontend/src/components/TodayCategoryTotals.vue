<script setup lang="ts">
import type { CategoryTotal } from '../types'

const props = defineProps<{ totals: CategoryTotal[] }>()

function formatRp(value: number): string {
  return `Rp ${Math.round(value).toLocaleString('id-ID')}`
}

function total(): number {
  return props.totals.reduce((sum, t) => sum + t.total, 0)
}
</script>

<template>
  <div class="section">
    <div class="header">
      <h3>Today's spend by category</h3>
      <span class="today-total">{{ formatRp(total()) }} total</span>
    </div>
    <p v-if="!totals.length" class="empty">No spending recorded today yet.</p>
    <div v-else class="grid">
      <div v-for="t in totals" :key="t.category" class="metric-card">
        <span class="label">{{ t.category }}</span>
        <span class="value">{{ formatRp(t.total) }}</span>
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

.header {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  margin-bottom: 1rem;
}

h3 {
  margin: 0;
  font-size: 1rem;
}

.today-total {
  color: var(--text-secondary);
  font-size: 0.85rem;
  font-weight: 600;
}

.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
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

.empty {
  color: var(--text-secondary);
  font-size: 0.9rem;
}
</style>
