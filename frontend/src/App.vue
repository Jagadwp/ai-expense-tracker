<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import {
  fetchAvailableMonths,
  fetchCategories,
  fetchCategoryPeriodComparison,
  fetchCategoryTotals,
  fetchCategoryTrend,
  fetchPeriodComparison,
  fetchSpendTrend,
  fetchTransactions,
} from './api'
import { DEFAULT_PRESET, PRESETS, presetRange } from './dateRange'
import FilterBar from './components/FilterBar.vue'
import PeriodComparisonMetrics from './components/PeriodComparisonMetrics.vue'
import CategoryPeriodMetrics from './components/CategoryPeriodMetrics.vue'
import CategoryChart from './components/CategoryChart.vue'
import TrendChart from './components/TrendChart.vue'
import CategoryTrendChart from './components/CategoryTrendChart.vue'
import TransactionTable from './components/TransactionTable.vue'
import TransactionPreviewModal from './components/TransactionPreviewModal.vue'
import QaChat from './components/QaChat.vue'
import type {
  CategoryPeriodComparison,
  CategoryTotal,
  CategoryTrendPoint,
  Filters,
  PeriodComparison,
  Transaction,
  TrendPoint,
} from './types'

const defaultRange = presetRange(PRESETS.find((p) => p.label === DEFAULT_PRESET)!, new Date())

const filters = ref<Filters>({
  category: null,
  dateFrom: defaultRange.dateFrom,
  dateTo: defaultRange.dateTo,
  sortBy: 'date',
  includeTransfers: false,
})

const categories = ref<string[]>([])
const availableMonths = ref<string[]>([])
const transactions = ref<Transaction[]>([])
const categoryTotals = ref<CategoryTotal[]>([])
const spendTrend = ref<TrendPoint[]>([])
const comparison = ref<PeriodComparison>({ current_total: 0, previous_total: 0 })
const categoryComparisons = ref<CategoryPeriodComparison[]>([])
const categoryTrend = ref<CategoryTrendPoint[]>([])

const loadError = ref<string | null>(null)
const previewMessageId = ref<string | null>(null)

async function onTransferUpdated() {
  await loadRangeDependent()
}

async function loadRangeDependent() {
  const [tx, totals, trend, comp, catComp, catTrend] = await Promise.all([
    fetchTransactions(filters.value),
    fetchCategoryTotals(filters.value),
    fetchSpendTrend(filters.value),
    fetchPeriodComparison(filters.value),
    fetchCategoryPeriodComparison(filters.value),
    fetchCategoryTrend(filters.value),
  ])
  transactions.value = tx
  categoryTotals.value = totals
  spendTrend.value = trend
  comparison.value = comp
  categoryComparisons.value = catComp
  categoryTrend.value = catTrend
}

async function loadAll() {
  try {
    loadError.value = null
    ;[categories.value, availableMonths.value] = await Promise.all([fetchCategories(), fetchAvailableMonths()])
    await loadRangeDependent()
  } catch (err) {
    loadError.value = err instanceof Error ? err.message : String(err)
  }
}

onMounted(loadAll)

watch(
  filters,
  async () => {
    try {
      loadError.value = null
      await loadRangeDependent()
    } catch (err) {
      loadError.value = err instanceof Error ? err.message : String(err)
    }
  },
  { deep: true },
)

const hasError = computed(() => loadError.value !== null)
</script>

<template>
  <div class="page">
    <header class="topbar">
      <h1>AI Expense Tracker</h1>
    </header>

    <main>
      <QaChat />

      <FilterBar :categories="categories" :available-months="availableMonths" :filters="filters" @update:filters="(f) => (filters = f)" />

      <p v-if="hasError" class="error">Failed to load dashboard data: {{ loadError }}</p>

      <template v-else>
        <PeriodComparisonMetrics :comparison="comparison" />

        <CategoryPeriodMetrics :comparisons="categoryComparisons" />

        <div class="charts">
          <CategoryChart :totals="categoryTotals" />
          <TrendChart :trend="spendTrend" />
        </div>

        <CategoryTrendChart :trend="categoryTrend" />

        <TransactionTable :transactions="transactions" @preview="(id) => (previewMessageId = id)" />
      </template>
    </main>

    <TransactionPreviewModal
      v-if="previewMessageId"
      :message-id="previewMessageId"
      @close="previewMessageId = null"
      @transfer-updated="onTransferUpdated"
    />
  </div>
</template>

<style scoped>
.page {
  min-height: 100vh;
}

.topbar {
  padding: 1.25rem 2rem;
  border-bottom: 1px solid var(--border);
  background: var(--surface);
}

.topbar h1 {
  font-size: 1.25rem;
}

main {
  max-width: 1200px;
  margin: 0 auto;
  padding: 1.5rem 2rem 3rem;
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
}

.charts {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 1.5rem;
}

.error {
  color: var(--danger);
}

@media (max-width: 800px) {
  .charts {
    grid-template-columns: 1fr;
  }
}
</style>
