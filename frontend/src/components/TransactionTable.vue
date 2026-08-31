<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { fetchTransactions } from '../api'
import type { SortColumn, SortDir, Transaction } from '../types'

const props = defineProps<{
  dateFrom: string
  dateTo: string
  category: string | null
  includeTransfers: boolean
  refreshKey: number
}>()

const emit = defineEmits<{
  preview: [messageId: string]
  edit: [tx: Transaction]
}>()

const COLUMNS: { key: SortColumn; label: string; defaultDir: SortDir }[] = [
  { key: 'date', label: 'Date', defaultDir: 'desc' },
  { key: 'merchant', label: 'Merchant', defaultDir: 'asc' },
  { key: 'category', label: 'Category', defaultDir: 'asc' },
  { key: 'amount', label: 'Amount', defaultDir: 'desc' },
  { key: 'payment_method', label: 'Payment method', defaultDir: 'asc' },
  { key: 'is_transfer', label: 'Transfer', defaultDir: 'desc' },
]

const PAGE_SIZE_OPTIONS = [10, 20, 50, 100]
const ALL_PAGE_SIZE = 100_000

const transactions = ref<Transaction[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const pageSizeSelection = computed(() => (pageSize.value === ALL_PAGE_SIZE ? 'all' : String(pageSize.value)))
const sortBy = ref<SortColumn>('date')
const sortDir = ref<SortDir>('desc')
const loading = ref(false)
const loadError = ref<string | null>(null)

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize.value)))

async function load() {
  loading.value = true
  try {
    loadError.value = null
    const result = await fetchTransactions({
      dateFrom: props.dateFrom,
      dateTo: props.dateTo,
      category: props.category,
      includeTransfers: props.includeTransfers,
      sortBy: sortBy.value,
      sortDir: sortDir.value,
      page: page.value,
      pageSize: pageSize.value,
    })
    transactions.value = result.items
    total.value = result.total
  } catch (err) {
    loadError.value = err instanceof Error ? err.message : String(err)
  } finally {
    loading.value = false
  }
}

onMounted(load)

watch(
  () => [props.dateFrom, props.dateTo, props.category, props.includeTransfers],
  () => {
    page.value = 1
    load()
  },
)

watch(() => props.refreshKey, load)

function sortByColumn(column: (typeof COLUMNS)[number]) {
  if (sortBy.value === column.key) {
    sortDir.value = sortDir.value === 'asc' ? 'desc' : 'asc'
  } else {
    sortBy.value = column.key
    sortDir.value = column.defaultDir
  }
  page.value = 1
  load()
}

function goToPage(p: number) {
  if (p < 1 || p > totalPages.value || p === page.value) return
  page.value = p
  load()
}

function onPageSizeChange(value: string) {
  pageSize.value = value === 'all' ? ALL_PAGE_SIZE : Number(value)
  page.value = 1
  load()
}

function formatRp(value: number | null): string {
  if (value === null) return ''
  return `Rp ${Math.round(value).toLocaleString('id-ID')}`
}

function formatDate(value: string | null): string {
  return value ? value.slice(0, 10) : ''
}
</script>

<template>
  <div class="table-card">
    <div class="header">
      <h3>Transactions</h3>
      <span class="total-count">{{ total }} total</span>
    </div>

    <p v-if="loadError" class="error">Failed to load transactions: {{ loadError }}</p>
    <p v-else-if="!loading && !transactions.length" class="empty">No transactions match the current filters.</p>
    <template v-else>
      <!-- Phones (≤600px): a table can't reflow into something readable at
           that width, so it's replaced by this card list instead — same
           data, same click-to-preview/edit actions. -->
      <div class="mobile-cards">
        <div
          v-for="tx in transactions"
          :key="tx.message_id"
          class="tx-card"
          @click="emit('preview', tx.message_id)"
        >
          <div class="tx-card-top">
            <span class="tx-date">{{ formatDate(tx.date) }}</span>
            <button class="edit-btn" title="Edit transaction" @click.stop="emit('edit', tx)">
              <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M12 20h9" />
                <path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4Z" />
              </svg>
            </button>
          </div>
          <div class="tx-card-main">
            <span class="tx-merchant">
              {{ tx.merchant ?? '' }}
              <span v-if="tx.is_manual" class="badge manual">manual</span>
            </span>
            <span class="tx-amount">{{ formatRp(tx.amount) }}</span>
          </div>
          <div class="tx-card-meta">
            <span v-if="tx.category" class="badge">{{ tx.category }}</span>
            <span v-if="tx.payment_method" class="tx-payment">{{ tx.payment_method }}</span>
            <span v-if="tx.is_transfer" class="badge transfer">transfer</span>
          </div>
        </div>
      </div>

      <table>
        <thead>
          <tr>
            <th>No.</th>
            <th></th>
            <th v-for="col in COLUMNS" :key="col.key" class="sortable" @click="sortByColumn(col)">
              {{ col.label }}
              <span v-if="sortBy === col.key" class="sort-indicator">{{ sortDir === 'asc' ? '▲' : '▼' }}</span>
            </th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="(tx, index) in transactions"
            :key="tx.message_id"
            class="row"
            @click="emit('preview', tx.message_id)"
          >
            <td class="no-col">{{ (page - 1) * pageSize + index + 1 }}</td>
            <td class="edit-col">
              <button class="edit-btn" title="Edit transaction" @click.stop="emit('edit', tx)">
                <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M12 20h9" />
                  <path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4Z" />
                </svg>
              </button>
            </td>
            <td>{{ formatDate(tx.date) }}</td>
            <td>
              {{ tx.merchant ?? '' }}
              <span v-if="tx.is_manual" class="badge manual">manual</span>
            </td>
            <td><span v-if="tx.category" class="badge">{{ tx.category }}</span></td>
            <td class="amount">{{ formatRp(tx.amount) }}</td>
            <td>{{ tx.payment_method ?? '' }}</td>
            <td>{{ tx.is_transfer ? 'yes' : '' }}</td>
          </tr>
        </tbody>
      </table>

      <div class="pagination">
        <label class="page-size">
          Rows per page
          <select :value="pageSizeSelection" @change="onPageSizeChange(($event.target as HTMLSelectElement).value)">
            <option v-for="opt in PAGE_SIZE_OPTIONS" :key="opt" :value="String(opt)">{{ opt }}</option>
            <option value="all">All</option>
          </select>
        </label>

        <div class="page-nav">
          <button :disabled="page === 1" @click="goToPage(page - 1)">Prev</button>
          <span>Page {{ page }} of {{ totalPages }}</span>
          <button :disabled="page === totalPages" @click="goToPage(page + 1)">Next</button>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.table-card {
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

.total-count {
  color: var(--text-secondary);
  font-size: 0.8rem;
}

table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.85rem;
}

th,
td {
  text-align: left;
  padding: 0.6rem 0.75rem;
  border-bottom: 1px solid var(--border);
}

th {
  color: var(--text-secondary);
  font-weight: 500;
  font-size: 0.8rem;
}

th.sortable {
  cursor: pointer;
  user-select: none;
  white-space: nowrap;
}

th.sortable:hover {
  color: var(--text-primary);
}

.sort-indicator {
  font-size: 0.65rem;
  color: var(--accent);
}

.no-col {
  width: 1%;
  color: var(--text-secondary);
  font-size: 0.8rem;
}

.edit-col {
  width: 1%;
}

.edit-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--border);
  background: var(--bg);
  color: var(--text-secondary);
  border-radius: 6px;
  padding: 0.35rem;
  line-height: 0;
}

.edit-btn:hover {
  border-color: var(--accent);
  color: var(--accent);
}

.row {
  cursor: pointer;
}

.row:hover {
  background: var(--bg);
}

.amount {
  font-weight: 500;
}

.badge {
  display: inline-block;
  background: var(--accent-soft);
  color: var(--accent);
  border-radius: 999px;
  padding: 0.15rem 0.6rem;
  font-size: 0.75rem;
  font-weight: 500;
}

.badge.manual {
  background: var(--bg);
  color: var(--text-secondary);
  border: 1px solid var(--border);
}

.badge.transfer {
  background: var(--accent-soft);
  color: var(--accent);
}

.mobile-cards {
  display: none;
}

.empty,
.error {
  color: var(--text-secondary);
  font-size: 0.85rem;
}

.error {
  color: var(--danger);
}

.pagination {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  margin-top: 1rem;
  font-size: 0.85rem;
  color: var(--text-secondary);
}

.page-size {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.page-size select {
  border: 1px solid var(--border);
  background: var(--bg);
  color: var(--text-primary);
  border-radius: 6px;
  padding: 0.3rem 0.5rem;
  font-size: 0.8rem;
}

.page-nav {
  display: flex;
  align-items: center;
  gap: 1rem;
}

.page-nav button {
  border: 1px solid var(--border);
  background: var(--bg);
  color: var(--text-primary);
  border-radius: 6px;
  padding: 0.3rem 0.8rem;
  font-size: 0.8rem;
}

.page-nav button:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.page-nav button:not(:disabled):hover {
  border-color: var(--accent);
  color: var(--accent);
}

@media (max-width: 600px) {
  .table-card {
    padding: 1rem;
  }

  table {
    display: none;
  }

  .mobile-cards {
    display: flex;
    flex-direction: column;
    gap: 0.6rem;
  }

  .tx-card {
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 0.75rem;
    cursor: pointer;
  }

  .tx-card-top {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 0.4rem;
  }

  .tx-date {
    font-size: 0.75rem;
    color: var(--text-secondary);
  }

  .tx-card-main {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 0.5rem;
  }

  .tx-merchant {
    font-size: 0.9rem;
    overflow-wrap: anywhere;
  }

  .tx-amount {
    font-weight: 600;
    white-space: nowrap;
  }

  .tx-card-meta {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    margin-top: 0.5rem;
    flex-wrap: wrap;
  }

  .tx-payment {
    font-size: 0.8rem;
    color: var(--text-secondary);
  }

  .pagination {
    flex-direction: column;
    align-items: stretch;
    gap: 0.6rem;
  }

  .page-nav {
    justify-content: space-between;
  }
}
</style>
