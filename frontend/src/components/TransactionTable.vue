<script setup lang="ts">
import type { Transaction } from '../types'

defineProps<{ transactions: Transaction[] }>()

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
    <h3>Transactions</h3>
    <p v-if="!transactions.length" class="empty">No transactions match the current filters.</p>
    <template v-else>
      <table>
        <thead>
          <tr>
            <th>Date</th>
            <th>Merchant</th>
            <th>Category</th>
            <th>Amount</th>
            <th>Payment method</th>
            <th>Transfer</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(tx, i) in transactions" :key="i">
            <td>{{ formatDate(tx.date) }}</td>
            <td>{{ tx.merchant ?? '' }}</td>
            <td><span v-if="tx.category" class="badge">{{ tx.category }}</span></td>
            <td class="amount">{{ formatRp(tx.amount) }}</td>
            <td>{{ tx.payment_method ?? '' }}</td>
            <td>{{ tx.is_transfer ? 'yes' : '' }}</td>
          </tr>
        </tbody>
      </table>
      <p class="caption">{{ transactions.length }} transaction(s)</p>
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

h3 {
  margin: 0 0 1rem;
  font-size: 1rem;
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

.empty,
.caption {
  color: var(--text-secondary);
  font-size: 0.85rem;
}
</style>
