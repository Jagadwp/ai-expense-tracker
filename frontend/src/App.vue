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
} from './api'
import { monthToDateRange } from './dateRange'
import FilterBar from './components/FilterBar.vue'
import PeriodComparisonMetrics from './components/PeriodComparisonMetrics.vue'
import CategoryPeriodMetrics from './components/CategoryPeriodMetrics.vue'
import CategoryChart from './components/CategoryChart.vue'
import TrendChart from './components/TrendChart.vue'
import CategoryTrendChart from './components/CategoryTrendChart.vue'
import TransactionTable from './components/TransactionTable.vue'
import TransactionPreviewModal from './components/TransactionPreviewModal.vue'
import TransactionFormModal from './components/TransactionFormModal.vue'
import QaChat from './components/QaChat.vue'
import SyncBar from './components/SyncBar.vue'
import type {
  CategoryPeriodComparison,
  CategoryTotal,
  CategoryTrendPoint,
  Filters,
  PeriodComparison,
  Transaction,
  TrendPoint,
} from './types'

const defaultRange = monthToDateRange(new Date())

const filters = ref<Filters>({
  category: null,
  dateFrom: defaultRange.dateFrom,
  dateTo: defaultRange.dateTo,
  includeTransfers: false,
})

const categories = ref<string[]>([])
const availableMonths = ref<string[]>([])
const categoryTotals = ref<CategoryTotal[]>([])
const spendTrend = ref<TrendPoint[]>([])
const comparison = ref<PeriodComparison>({ current_total: 0, previous_total: 0 })
const categoryComparisons = ref<CategoryPeriodComparison[]>([])
const categoryTrend = ref<CategoryTrendPoint[]>([])

const loadError = ref<string | null>(null)
const previewMessageId = ref<string | null>(null)
const showAddModal = ref(false)
const editingTransaction = ref<Transaction | null>(null)
const transactionsRefreshKey = ref(0)

async function onTransactionsChanged() {
  transactionsRefreshKey.value++
  await loadRangeDependent()
}

function onTransactionAdded() {
  showAddModal.value = false
  onTransactionsChanged()
}

function onTransactionEdited() {
  editingTransaction.value = null
  onTransactionsChanged()
}

async function loadRangeDependent() {
  const [totals, trend, comp, catComp, catTrend] = await Promise.all([
    fetchCategoryTotals(filters.value),
    fetchSpendTrend(filters.value),
    fetchPeriodComparison(filters.value),
    fetchCategoryPeriodComparison(filters.value),
    fetchCategoryTrend(filters.value),
  ])
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

        <div class="transactions-header">
          <h2>Transactions</h2>
          <div class="transactions-actions">
            <button class="add-btn" @click="showAddModal = true">+ Add transaction</button>
            <SyncBar @synced="onTransactionsChanged" />
          </div>
        </div>

        <TransactionTable
          :date-from="filters.dateFrom"
          :date-to="filters.dateTo"
          :category="filters.category"
          :include-transfers="filters.includeTransfers"
          :refresh-key="transactionsRefreshKey"
          @preview="(id) => (previewMessageId = id)"
          @edit="(tx) => (editingTransaction = tx)"
        />
      </template>
    </main>

    <TransactionPreviewModal
      v-if="previewMessageId"
      :message-id="previewMessageId"
      @close="previewMessageId = null"
      @changed="onTransactionsChanged"
    />

    <TransactionFormModal
      v-if="showAddModal"
      @saved="onTransactionAdded"
      @close="showAddModal = false"
    />

    <TransactionFormModal
      v-if="editingTransaction"
      :editing="editingTransaction"
      @saved="onTransactionEdited"
      @close="editingTransaction = null"
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

.transactions-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 1rem;
  flex-wrap: wrap;
}

.transactions-header h2 {
  font-size: 1rem;
  font-weight: 600;
}

.transactions-actions {
  display: flex;
  align-items: flex-start;
  gap: 0.75rem;
}

.add-btn {
  border: 1px solid var(--accent);
  background: var(--accent-soft);
  color: var(--accent);
  font-weight: 600;
  border-radius: 8px;
  padding: 0.5rem 0.9rem;
  font-size: 0.8rem;
  white-space: nowrap;
}

.add-btn:hover {
  background: var(--accent);
  color: #fff;
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
