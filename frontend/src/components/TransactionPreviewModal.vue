<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { fetchTransactionDetail, setIsTransfer } from '../api'
import type { TransactionDetail } from '../types'

const props = defineProps<{ messageId: string }>()

const emit = defineEmits<{
  close: []
  'transfer-updated': []
}>()

const detail = ref<TransactionDetail | null>(null)
const loadError = ref<string | null>(null)
const saving = ref(false)

async function load() {
  try {
    loadError.value = null
    detail.value = await fetchTransactionDetail(props.messageId)
  } catch (err) {
    loadError.value = err instanceof Error ? err.message : String(err)
  }
}

onMounted(load)

async function toggleTransfer() {
  if (!detail.value) return
  saving.value = true
  try {
    const next = !detail.value.is_transfer
    await setIsTransfer(props.messageId, next)
    detail.value.is_transfer = next
    emit('transfer-updated')
  } catch (err) {
    loadError.value = err instanceof Error ? err.message : String(err)
  } finally {
    saving.value = false
  }
}

function formatRp(value: number | null): string {
  if (value === null) return ''
  return `Rp ${Math.round(value).toLocaleString('id-ID')}`
}
</script>

<template>
  <div class="overlay" @click.self="emit('close')">
    <div class="modal">
      <header>
        <h3>Email preview</h3>
        <button class="close" @click="emit('close')">✕</button>
      </header>

      <p v-if="loadError" class="error">{{ loadError }}</p>

      <div v-else-if="detail" class="body">
        <div class="details">
          <dl class="meta">
            <div><dt>Subject</dt><dd>{{ detail.raw_subject }}</dd></div>
            <div><dt>From</dt><dd>{{ detail.raw_from }}</dd></div>
            <div><dt>Date</dt><dd>{{ detail.date?.slice(0, 10) }}</dd></div>
            <div><dt>Merchant</dt><dd>{{ detail.merchant }}</dd></div>
            <div><dt>Category</dt><dd>{{ detail.category }}</dd></div>
            <div><dt>Amount</dt><dd>{{ formatRp(detail.amount) }}</dd></div>
            <div><dt>Payment method</dt><dd>{{ detail.payment_method }}</dd></div>
          </dl>

          <div class="transfer-action">
            <span v-if="detail.is_transfer" class="badge transfer">Marked as transfer</span>
            <button class="toggle" :class="{ active: detail.is_transfer }" :disabled="saving" @click="toggleTransfer">
              {{ detail.is_transfer ? 'Unmark as transfer' : 'Mark as transfer' }}
            </button>
          </div>
        </div>

        <iframe class="preview-frame" sandbox="" :srcdoc="detail.raw_body ?? ''" title="Email body preview" />
      </div>

      <p v-else class="loading">Loading…</p>
    </div>
  </div>
</template>

<style scoped>
.overlay {
  position: fixed;
  inset: 0;
  background: rgba(17, 24, 39, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 2rem;
  z-index: 100;
}

.modal {
  background: var(--surface);
  border-radius: var(--radius);
  box-shadow: var(--shadow);
  width: 100%;
  max-width: 1080px;
  max-height: 90vh;
  display: flex;
  flex-direction: column;
  padding: 1.5rem;
  gap: 1rem;
  overflow: hidden;
}

header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

header h3 {
  font-size: 1.1rem;
}

.close {
  border: none;
  background: transparent;
  font-size: 1rem;
  color: var(--text-secondary);
  padding: 0.25rem 0.5rem;
  border-radius: 6px;
}

.close:hover {
  background: var(--bg);
}

.body {
  display: grid;
  grid-template-columns: 320px 1fr;
  gap: 1.5rem;
  flex: 1;
  min-height: 0;
}

.details {
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
  overflow-y: auto;
}

.meta {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  margin: 0;
}

.meta dt {
  font-size: 0.75rem;
  color: var(--text-secondary);
}

.meta dd {
  margin: 0;
  font-size: 0.9rem;
  word-break: break-word;
}

.transfer-action {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 0.6rem;
}

.badge.transfer {
  background: var(--accent-soft);
  color: var(--accent);
  border-radius: 999px;
  padding: 0.2rem 0.7rem;
  font-size: 0.75rem;
  font-weight: 500;
}

.toggle {
  border: 1.5px solid var(--accent);
  background: var(--accent-soft);
  color: var(--accent);
  font-weight: 600;
  border-radius: 8px;
  padding: 0.5rem 1rem;
  font-size: 0.85rem;
}

.toggle:hover {
  background: var(--accent);
  color: #fff;
}

.toggle.active {
  background: var(--accent);
  color: #fff;
}

.toggle.active:hover {
  background: var(--accent-soft);
  color: var(--accent);
}

.toggle:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.preview-frame {
  width: 100%;
  height: 100%;
  min-height: 420px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: #fff;
}

.error {
  color: var(--danger);
}

.loading {
  color: var(--text-secondary);
}

@media (max-width: 700px) {
  .body {
    grid-template-columns: 1fr;
    overflow-y: auto;
  }
}
</style>
