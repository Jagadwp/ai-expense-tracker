<script setup lang="ts">
import { onUnmounted, ref } from 'vue'
import { fetchSyncProgress, runExtraction, syncAndExtract } from '../api'
import type { SyncAndExtractResult, SyncProgress } from '../types'

const WINDOWS = ['1d', '7d', '14d', '30d', '90d']
const EXTRACT_BATCH_SIZE = 50
const POLL_INTERVAL_MS = 500

const emit = defineEmits<{
  synced: []
}>()

const selectedWindow = ref('7d')
const syncing = ref(false)
const extractingMore = ref(false)
const result = ref<SyncAndExtractResult | null>(null)
const error = ref<string | null>(null)
const progress = ref<SyncProgress | null>(null)

let pollTimer: ReturnType<typeof setInterval> | null = null

function startPolling() {
  progress.value = null
  pollTimer = setInterval(async () => {
    try {
      const p = await fetchSyncProgress()
      progress.value = p.total > 0 ? p : null
    } catch {
      // Best-effort UI indicator — a transient poll failure isn't worth surfacing.
    }
  }, POLL_INTERVAL_MS)
}

function stopPolling() {
  if (pollTimer !== null) {
    clearInterval(pollTimer)
    pollTimer = null
  }
  progress.value = null
}

onUnmounted(stopPolling)

async function syncNow() {
  syncing.value = true
  error.value = null
  result.value = null
  startPolling()
  try {
    result.value = await syncAndExtract(selectedWindow.value, EXTRACT_BATCH_SIZE)
    emit('synced')
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err)
  } finally {
    syncing.value = false
    stopPolling()
  }
}

async function extractMore() {
  if (!result.value) return
  extractingMore.value = true
  error.value = null
  startPolling()
  try {
    const extraction = await runExtraction(EXTRACT_BATCH_SIZE)
    result.value = { ...result.value, extraction }
    emit('synced')
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err)
  } finally {
    extractingMore.value = false
    stopPolling()
  }
}
</script>

<template>
  <div class="sync-bar">
    <div class="controls">
      <select v-model="selectedWindow" :disabled="syncing">
        <option v-for="w in WINDOWS" :key="w" :value="w">Last {{ w }}</option>
      </select>
      <button class="sync-btn" :disabled="syncing" @click="syncNow">
        {{ syncing ? 'Syncing…' : 'Sync now' }}
      </button>
    </div>

    <p v-if="progress" class="progress">Syncing {{ progress.processed }} of {{ progress.total }} emails…</p>

    <p v-else-if="error" class="error">{{ error }}</p>

    <div v-else-if="result" class="summary">
      <span>
        Fetched {{ result.sync.emails_fetched }}, new {{ result.sync.emails_new }} · extracted
        {{ result.extraction.extracted }}, flagged {{ result.extraction.flagged_low_confidence }},
        <span :class="{ failed: result.extraction.failed > 0 }">failed {{ result.extraction.failed }}</span>
      </span>
      <button
        v-if="result.extraction.remaining_unextracted > 0"
        class="extract-more"
        :disabled="extractingMore"
        @click="extractMore"
      >
        {{ extractingMore ? 'Extracting…' : `Extract ${Math.min(result.extraction.remaining_unextracted, EXTRACT_BATCH_SIZE)} more` }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.sync-bar {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 0.5rem;
}

.controls {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

select {
  border: 1px solid var(--border);
  background: var(--bg);
  color: var(--text-primary);
  border-radius: 6px;
  padding: 0.35rem 0.5rem;
  font-size: 0.8rem;
}

.sync-btn {
  border: none;
  background: var(--accent);
  color: #fff;
  border-radius: 6px;
  padding: 0.4rem 0.9rem;
  font-size: 0.8rem;
  font-weight: 600;
}

.sync-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.summary {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  font-size: 0.8rem;
  color: var(--text-secondary);
}

.summary .failed {
  color: var(--danger);
  font-weight: 600;
}

.extract-more {
  border: 1px solid var(--accent);
  background: var(--accent-soft);
  color: var(--accent);
  border-radius: 6px;
  padding: 0.3rem 0.7rem;
  font-size: 0.75rem;
  font-weight: 600;
}

.extract-more:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.error {
  color: var(--danger);
  font-size: 0.8rem;
  margin: 0;
  max-width: 360px;
  text-align: right;
}

.progress {
  color: var(--text-secondary);
  font-size: 0.8rem;
  margin: 0;
}
</style>
