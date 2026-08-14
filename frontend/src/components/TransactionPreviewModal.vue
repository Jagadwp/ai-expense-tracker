<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { deleteTransaction, fetchTransactionDetail, setIsTransfer } from '../api'
import type { TransactionDetail } from '../types'
import TransactionFormModal from './TransactionFormModal.vue'

const props = defineProps<{ messageId: string }>()

const emit = defineEmits<{
  close: []
  changed: []
}>()

const detail = ref<TransactionDetail | null>(null)
const loadError = ref<string | null>(null)
const saving = ref(false)
const deleting = ref(false)
const editing = ref(false)
const copied = ref(false)

// Only a real, non-empty email body is worth the wide two-column layout —
// otherwise the right column would just be blank space.
const hasFrame = computed(() => !!detail.value && !detail.value.is_manual && !!detail.value.raw_body)

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
    emit('changed')
  } catch (err) {
    loadError.value = err instanceof Error ? err.message : String(err)
  } finally {
    saving.value = false
  }
}

async function remove() {
  if (!detail.value) return
  if (!confirm('Delete this transaction? This cannot be undone.')) return
  deleting.value = true
  try {
    await deleteTransaction(props.messageId)
    emit('changed')
    emit('close')
  } catch (err) {
    loadError.value = err instanceof Error ? err.message : String(err)
  } finally {
    deleting.value = false
  }
}

function onEdited() {
  editing.value = false
  emit('changed')
  load()
}

function formatRp(value: number | null): string {
  if (value === null) return ''
  return `Rp ${Math.round(value).toLocaleString('id-ID')}`
}

async function copyId() {
  if (!detail.value) return
  await navigator.clipboard.writeText(detail.value.message_id)
  copied.value = true
  setTimeout(() => {
    copied.value = false
  }, 1200)
}
</script>

<template>
  <div class="overlay" @click.self="emit('close')">
    <div class="modal" :class="{ compact: !hasFrame }">
      <header>
        <h3>Email preview</h3>
        <button class="close" @click="emit('close')">✕</button>
      </header>

      <p v-if="loadError" class="error">{{ loadError }}</p>

      <div v-else-if="detail" class="body" :class="{ 'manual-only': !hasFrame }">
        <div class="details">
          <dl class="meta">
            <div>
              <dt>ID</dt>
              <dd class="id-row">
                <span class="id-text">{{ detail.message_id }}</span>
                <button class="copy-btn" title="Copy ID" @click="copyId">
                  <span v-if="copied" class="copied-label">copied</span>
                  <svg v-else viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
                    <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
                  </svg>
                </button>
              </dd>
            </div>
            <div v-if="!detail.is_manual"><dt>Subject</dt><dd>{{ detail.raw_subject }}</dd></div>
            <div v-if="!detail.is_manual"><dt>From</dt><dd>{{ detail.raw_from }}</dd></div>
            <div><dt>Date</dt><dd>{{ detail.date?.slice(0, 10) }}</dd></div>
            <div><dt>Merchant</dt><dd>{{ detail.merchant }}</dd></div>
            <div><dt>Category</dt><dd>{{ detail.category }}</dd></div>
            <div><dt>Amount</dt><dd>{{ formatRp(detail.amount) }}</dd></div>
            <div><dt>Payment method</dt><dd>{{ detail.payment_method }}</dd></div>
          </dl>

          <div class="transfer-action">
            <span v-if="detail.is_manual" class="badge manual">Manually added</span>
            <span v-if="detail.is_transfer" class="badge transfer">Marked as transfer</span>
            <button class="toggle" :class="{ active: detail.is_transfer }" :disabled="saving" @click="toggleTransfer">
              {{ detail.is_transfer ? 'Unmark as transfer' : 'Mark as transfer' }}
            </button>
          </div>

          <div class="row-actions">
            <button class="edit" @click="editing = true">Edit</button>
            <button class="delete" :disabled="deleting" @click="remove">{{ deleting ? 'Deleting…' : 'Delete' }}</button>
          </div>
        </div>

        <iframe
          v-if="hasFrame"
          class="preview-frame"
          sandbox=""
          :srcdoc="detail.raw_body ?? ''"
          title="Email body preview"
        />
      </div>

      <p v-else class="loading">Loading…</p>
    </div>

    <TransactionFormModal
      v-if="editing && detail"
      :editing="detail"
      @saved="onEdited"
      @close="editing = false"
    />
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

.modal.compact {
  max-width: 500px;
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

.body.manual-only {
  grid-template-columns: 1fr;
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

.id-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.id-text {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 0.8rem;
  word-break: break-all;
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
  padding: 0.25rem 0.4rem;
  line-height: 0;
}

.copy-btn:hover {
  border-color: var(--accent);
  color: var(--accent);
}

.copied-label {
  font-size: 0.7rem;
  line-height: 1;
  color: var(--accent);
  font-weight: 600;
}

.transfer-action {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 0.6rem;
}

.badge.transfer,
.badge.manual {
  background: var(--accent-soft);
  color: var(--accent);
  border-radius: 999px;
  padding: 0.2rem 0.7rem;
  font-size: 0.75rem;
  font-weight: 500;
}

.row-actions {
  display: flex;
  gap: 0.6rem;
}

.edit,
.delete {
  border: 1px solid var(--border);
  background: var(--bg);
  color: var(--text-primary);
  border-radius: 8px;
  padding: 0.5rem 1rem;
  font-size: 0.85rem;
}

.edit:hover {
  border-color: var(--accent);
  color: var(--accent);
}

.delete {
  color: var(--danger);
}

.delete:hover {
  border-color: var(--danger);
}

.delete:disabled {
  opacity: 0.6;
  cursor: not-allowed;
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
  min-height: 500px;
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
