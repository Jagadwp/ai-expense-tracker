<script setup lang="ts">
import { nextTick, ref } from 'vue'
import { askQuestion } from '../api'
import type { QaExchange, QaTurn } from '../types'

// How many prior exchanges to send as follow-up context — mirrors
// MAX_HISTORY_TURNS in app/qa_agent.py (the backend caps it too; this just
// avoids sending more than necessary).
const MAX_HISTORY_TURNS = 5

const question = ref('')
const exchanges = ref<QaExchange[]>([])
const asking = ref(false)
const listEl = ref<HTMLElement | null>(null)

async function scrollToBottom() {
  await nextTick()
  listEl.value?.scrollTo({ top: listEl.value.scrollHeight, behavior: 'smooth' })
}

function recentHistory(): QaTurn[] {
  return exchanges.value
    .filter((ex): ex is QaExchange & { answer: string } => ex.answer !== null && !ex.error)
    .slice(-MAX_HISTORY_TURNS)
    .map((ex) => ({ question: ex.question, answer: ex.answer }))
}

async function ask() {
  const q = question.value.trim()
  if (!q || asking.value) return

  const history = recentHistory()
  const exchange: QaExchange = { question: q, answer: null, sql: null, error: null }
  exchanges.value.push(exchange)
  question.value = ''
  asking.value = true
  await scrollToBottom()

  try {
    const result = await askQuestion(q, history)
    exchange.answer = result.answer
    exchange.sql = result.sql
  } catch (err) {
    exchange.error = err instanceof Error ? err.message : String(err)
  } finally {
    asking.value = false
    await scrollToBottom()
  }
}

function newChat() {
  exchanges.value = []
}
</script>

<template>
  <div class="qa-card">
    <div class="header">
      <h3>Ask about your expenses</h3>
      <button v-if="exchanges.length" type="button" class="new-chat" @click="newChat">New chat</button>
    </div>

    <div v-if="exchanges.length" ref="listEl" class="exchanges">
      <div v-for="(ex, i) in exchanges" :key="i" class="exchange">
        <div class="bubble question">{{ ex.question }}</div>
        <div v-if="ex.error" class="bubble answer error">{{ ex.error }}</div>
        <div v-else-if="ex.answer !== null" class="bubble answer">
          {{ ex.answer }}
          <details v-if="ex.sql" class="sql">
            <summary>SQL used</summary>
            <code>{{ ex.sql }}</code>
          </details>
        </div>
        <div v-else class="bubble answer loading">Thinking…</div>
      </div>
    </div>
    <p v-else class="empty">Ask things like "how much did I spend on food last month?"</p>

    <form class="composer" @submit.prevent="ask">
      <label for="qa-question" class="sr-only">Ask a question about your expenses</label>
      <input
        id="qa-question"
        v-model="question"
        type="text"
        placeholder="Ask a question about your expenses…"
        :disabled="asking"
      />
      <button type="submit" :disabled="asking || !question.trim()">Ask</button>
    </form>
  </div>
</template>

<style scoped>
.qa-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  box-shadow: var(--shadow);
  padding: 1.5rem;
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

h3 {
  margin: 0;
  font-size: 1rem;
}

.header {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
}

.new-chat {
  border: 1px solid var(--border);
  background: var(--bg);
  color: var(--text-secondary);
  border-radius: 8px;
  padding: 0.3rem 0.7rem;
  font-size: 0.8rem;
}

.new-chat:hover {
  border-color: var(--accent);
  color: var(--accent);
}

.exchanges {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  max-height: 320px;
  overflow-y: auto;
}

.exchange {
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
}

.bubble {
  max-width: 80%;
  padding: 0.6rem 0.9rem;
  border-radius: 10px;
  font-size: 0.9rem;
  line-height: 1.4;
}

.bubble.question {
  align-self: flex-end;
  background: var(--accent);
  color: #fff;
}

.bubble.answer {
  align-self: flex-start;
  background: var(--bg);
  color: var(--text-primary);
}

.bubble.answer.error {
  background: #fef2f2;
  color: var(--danger);
}

.bubble.answer.loading {
  color: var(--text-secondary);
}

.sql {
  margin-top: 0.5rem;
  font-size: 0.75rem;
  color: var(--text-secondary);
}

.sql summary {
  cursor: pointer;
}

.sql code {
  display: block;
  margin-top: 0.4rem;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}

.empty {
  color: var(--text-secondary);
  font-size: 0.9rem;
  margin: 0;
}

.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}

.composer {
  display: flex;
  gap: 0.6rem;
}

.composer input {
  flex: 1;
  border: 1px solid var(--border);
  background: var(--bg);
  color: var(--text-primary);
  border-radius: 8px;
  padding: 0.5rem 0.75rem;
  font-size: 0.9rem;
}

.composer button {
  border: none;
  background: var(--accent);
  color: #fff;
  border-radius: 8px;
  padding: 0.5rem 1.2rem;
  font-size: 0.9rem;
  font-weight: 600;
}

.composer button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>
