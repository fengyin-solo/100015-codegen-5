<template>
  <section class="page" data-module="temperature">
    <header class="page-head">
      <div>
        <h2>温控监控管理</h2>
        <p class="page-desc">维护温控记录，围绕记录编号、关联运单、测点编号、实时温度做登记、筛选与状态流转；支持按运单查看测点温度概览。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记温控记录</button>
        <button class="btn" type="button" @click="exportRows">导出温控监控清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <section class="overview-panel">
      <header class="overview-head">
        <div>
          <h3>测点温度概览</h3>
          <p class="page-desc">按运单汇总各测点的实时温度与上下限，偏高幅度大的测点排在最前。</p>
        </div>
        <div class="overview-tools">
          <label class="filter-item">
            <span>运单</span>
            <select v-model="selectedWaybill" @change="loadOverview">
              <option v-if="!waybillOptions.length" value="" disabled>暂无运单</option>
              <option v-for="option in waybillOptions" :key="option" :value="option">{{ option }}</option>
            </select>
          </label>
          <button class="btn ghost" type="button" @click="loadOverview">刷新概览</button>
        </div>
      </header>

      <div v-if="overviewError" class="overview-error">
        <span class="error-text">{{ overviewError }}</span>
        <button class="btn" type="button" @click="loadOverview">重新加载</button>
      </div>

      <template v-else-if="overview">
        <div class="overview-status">
          <span
            v-for="status in statuses"
            :key="status"
            class="status-chip"
            :class="statusClass(status)"
          >
            {{ status }} {{ overview.status_counts[status] ?? 0 }}
          </span>
        </div>

        <p v-if="!overview.points.length" class="empty-state overview-empty">
          {{ overview.message ?? '该运单暂无测点明细' }}
        </p>

        <table v-else class="data-table overview-table">
          <thead>
            <tr>
              <th v-for="column in overviewColumns" :key="column">{{ column }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="point in overview.points" :key="String(point.id)">
              <td>{{ point.测点编号 ?? '—' }}</td>
              <td>
                <button
                  class="link temp-link"
                  :class="statusClass(point.status)"
                  type="button"
                  @click="openRecord(point)"
                >
                  {{ point.实时温度 ?? '—' }}
                </button>
              </td>
              <td>{{ point.温度上限 ?? '—' }}</td>
              <td>{{ point.温度下限 ?? '—' }}</td>
              <td>
                <span class="status-chip" :class="statusClass(point.status)">{{ point.status }}</span>
              </td>
              <td>{{ point.偏高幅度 != null ? `+${point.偏高幅度}` : '—' }}</td>
            </tr>
          </tbody>
        </table>
      </template>

      <section v-if="recordDetail || detailError || detailLoading" class="record-detail">
        <header class="record-detail-head">
          <strong>温控记录详情</strong>
          <button class="link" type="button" @click="closeRecord">关闭</button>
        </header>
        <p v-if="detailLoading" class="page-desc">记录加载中…</p>
        <p v-else-if="detailError" class="error-text">{{ detailError }}</p>
        <dl v-else-if="recordDetail" class="record-detail-grid">
          <template v-for="column in columns" :key="column">
            <dt>{{ column }}</dt>
            <dd>{{ recordDetail[column] ?? '—' }}</dd>
          </template>
          <dt>记录状态</dt>
          <dd>
            <span class="status-chip" :class="statusClass(String(recordDetail.status ?? '正常'))">
              {{ recordDetail.status ?? '正常' }}
            </span>
          </dd>
        </dl>
      </section>
    </section>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td class="row-actions">
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无温控监控数据，可先登记温控记录</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条温控监控记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>

type OverviewPoint = {
  id: number
  记录编号: string | null
  测点编号: string | null
  实时温度: number | null
  温度上限: number | null
  温度下限: number | null
  采集时间: string | null
  status: string
  偏高幅度: number | null
}

type WaybillOverview = {
  waybill: string | null
  waybill_options: string[]
  total: number
  status_counts: Record<string, number>
  points: OverviewPoint[]
  message: string | null
}

const ENDPOINT = '/api/temperature'
const columns = ["记录编号", "关联运单", "测点编号", "实时温度", "温度上限", "温度下限", "采集时间"]
const overviewColumns = ["测点编号", "实时温度", "温度上限", "温度下限", "测点状态", "偏高幅度"]
const actions = ["确认记录", "标记超限", "重新采集"]
const statuses = ["正常", "偏高", "偏低", "已离线"]
const stats = [{"label": "今日采集测点", "value": 0}, {"label": "超限测点", "value": 0}, {"label": "离线测点", "value": 0}]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)

const overview = ref<WaybillOverview | null>(null)
const overviewError = ref('')
const selectedWaybill = ref('')
const waybillOptions = ref<string[]>([])
const recordDetail = ref<Row | null>(null)
const detailError = ref('')
const detailLoading = ref(false)

const STATUS_CLASS: Record<string, string> = {
  正常: 'status-normal',
  偏高: 'status-high',
  偏低: 'status-low',
  已离线: 'status-offline',
}

function statusClass(status: string) {
  return STATUS_CLASS[status] ?? 'status-normal'
}

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '温控记录登记入口尚未接入审批流'
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
    if (!response.ok) {
      throw new Error('温控监控动作未生效，请稍后重试')
    }
    await reload()
    await loadOverview()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '温控监控操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('温控记录列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '温控监控列表读取失败'
  }
}

async function loadOverview() {
  overviewError.value = ''
  const query = selectedWaybill.value
    ? `?waybill=${encodeURIComponent(selectedWaybill.value)}`
    : ''
  try {
    const response = await request(`${ENDPOINT}/overview${query}`)
    if (!response.ok) {
      throw new Error('测点温度概览读取失败')
    }
    const payload = (await response.json()) as WaybillOverview
    overview.value = payload
    waybillOptions.value = payload.waybill_options ?? []
    selectedWaybill.value = payload.waybill ?? ''
    closeRecord()
  } catch (error) {
    overviewError.value = error instanceof Error ? error.message : '测点温度概览读取失败'
  }
}

async function openRecord(point: OverviewPoint) {
  recordDetail.value = null
  detailError.value = ''
  detailLoading.value = true
  try {
    const response = await request(`${ENDPOINT}/${point.id}`)
    if (!response.ok) {
      throw new Error(`温控记录 ${point.记录编号 ?? point.id} 读取失败`)
    }
    recordDetail.value = (await response.json()) as Row
  } catch (error) {
    detailError.value = error instanceof Error ? error.message : '温控记录读取失败'
  } finally {
    detailLoading.value = false
  }
}

function closeRecord() {
  recordDetail.value = null
  detailError.value = ''
  detailLoading.value = false
}

onMounted(() => {
  void reload()
  void loadOverview()
})
</script>
