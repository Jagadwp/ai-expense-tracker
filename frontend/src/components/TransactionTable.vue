<script setup lang="ts">
import { ref } from 'vue'
import type { Transaction } from '../types'

defineProps<{ transactions: Transaction[] }>()

const emit = defineEmits<{
  preview: [messageId: string]
}>()

const copiedId = ref<string | null>(null)

async function copyId(messageId: string) {
  await navigator.clipboard.writeText(messageId)
  copiedId.value = messageId
  setTimeout(() => {
    if (copiedId.value === messageId) copiedId.value = null
  }, 1200)
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
    <h3>Transactions</h3>
    <p v-if="!transactions.length" class="empty">No transactions match the current filters.</p>
    <template v-else>
      <table>
        <thead>
          <tr>
            <th>ID</th>
            <th>Date</th>
            <th>Merchant</th>
            <th>Category</th>
            <th>Amount</th>
            <th>Payment method</th>
            <th>Transfer</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="tx in transactions" :key="tx.message_id" class="row" @click="emit('preview', tx.message_id)">
            <td class="id">
              <span class="id-text">{{ tx.message_id }}</span>
              <button class="copy-btn" title="Copy ID" @click.stop="copyId(tx.message_id)">
                <svg v-if="copiedId !== tx.message_id" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
                  <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
                </svg>
                <svg v-else viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <polyline points="20 6 9 17 4 12" />
                </svg>
              </button>
            </td>
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

.id {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 0.75rem;
  color: var(--text-secondary);
}

.copy-btn {
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--border);
  background: var(--bg);
  color: var(--text-secondary);
  border-radius: 6px;
  padding: 0.25rem;
  line-height: 0;
}

.copy-btn:hover {
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

.empty,
.caption {
  color: var(--text-secondary);
  font-size: 0.85rem;
}
</style>
