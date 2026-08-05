<script setup lang="ts">
import { computed } from 'vue'
import { formatMonthLabel, matchedMonth, monthRange, PRESETS, presetRange, toIsoDate } from '../dateRange'
import type { Filters } from '../types'

const props = defineProps<{
  categories: string[]
  availableMonths: string[]
  filters: Filters
}>()

const emit = defineEmits<{
  'update:filters': [Filters]
}>()

function update(partial: Partial<Filters>) {
  emit('update:filters', { ...props.filters, ...partial })
}

function applyPreset(preset: (typeof PRESETS)[number]) {
  update(presetRange(preset, new Date()))
}

function applyMonth(yyyyMm: string) {
  if (!yyyyMm) return
  update(monthRange(yyyyMm))
}

const selectedMonth = computed(() => matchedMonth(props.filters.dateFrom, props.filters.dateTo))

const activePreset = computed(() => {
  if (selectedMonth.value) return '1M'
  const today = new Date()
  return PRESETS.find((p) => {
    const range = presetRange(p, today)
    return range.dateFrom === props.filters.dateFrom && range.dateTo === toIsoDate(today)
  })?.label
})
</script>

<template>
  <div class="filter-bar">
    <div class="group presets">
      <button
        v-for="preset in PRESETS"
        :key="preset.label"
        class="preset"
        :class="{ active: activePreset === preset.label }"
        @click="applyPreset(preset)"
      >
        {{ preset.label }}
      </button>
    </div>

    <div class="group range">
      <input type="date" :value="filters.dateFrom" :max="filters.dateTo" @change="update({ dateFrom: ($event.target as HTMLInputElement).value })" />
      <span class="dash">–</span>
      <input type="date" :value="filters.dateTo" :min="filters.dateFrom" @change="update({ dateTo: ($event.target as HTMLInputElement).value })" />
    </div>

    <div class="group">
      <select :value="selectedMonth ?? ''" @change="applyMonth(($event.target as HTMLSelectElement).value)">
        <option value="" disabled>By month</option>
        <option v-for="m in availableMonths" :key="m" :value="m">{{ formatMonthLabel(m) }}</option>
      </select>
    </div>

    <div class="group">
      <select :value="filters.category ?? ''" @change="update({ category: ($event.target as HTMLSelectElement).value || null })">
        <option value="">All categories</option>
        <option v-for="c in categories" :key="c" :value="c">{{ c }}</option>
      </select>
    </div>

    <div class="group">
      <select :value="filters.sortBy" @change="update({ sortBy: ($event.target as HTMLSelectElement).value as Filters['sortBy'] })">
        <option value="date">Sort: date</option>
        <option value="amount">Sort: amount</option>
      </select>
    </div>

    <label class="checkbox">
      <input
        type="checkbox"
        :checked="filters.includeTransfers"
        @change="update({ includeTransfers: ($event.target as HTMLInputElement).checked })"
      />
      Include transfers
    </label>
  </div>
</template>

<style scoped>
.filter-bar {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  flex-wrap: wrap;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  box-shadow: var(--shadow);
  padding: 0.75rem 1rem;
}

.group {
  display: flex;
  align-items: center;
  gap: 0.4rem;
}

.presets {
  gap: 0.25rem;
  background: var(--bg);
  border-radius: 8px;
  padding: 0.2rem;
}

.preset {
  border: none;
  background: transparent;
  color: var(--text-secondary);
  font-size: 0.85rem;
  font-weight: 500;
  padding: 0.35rem 0.7rem;
  border-radius: 6px;
}

.preset:hover {
  color: var(--text-primary);
}

.preset.active {
  background: var(--accent);
  color: #fff;
}

.range {
  color: var(--text-secondary);
}

.dash {
  color: var(--text-secondary);
}

input[type='date'],
select {
  background: var(--surface);
  color: var(--text-primary);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 0.4rem 0.6rem;
  font-size: 0.85rem;
}

.checkbox {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.85rem;
  color: var(--text-secondary);
  margin-left: auto;
}
</style>
