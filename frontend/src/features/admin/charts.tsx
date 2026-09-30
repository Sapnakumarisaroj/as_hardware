/**
 * Charts (Recharts). This module is loaded on demand by the dashboard and analytics pages only,
 * so the chart library never reaches customers. Every chart is drawn from API data and comes with
 * the same numbers as a table (see ChartWithTable), for screen readers and for checking.
 */
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ComposedChart,
  Legend,
  Line,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import { formatPrice } from '@/lib/format'

import type { SeriesRow } from './types'

const INK = '#1c1f24'
const AMBER = '#f5a300'
const STEEL = '#8a929d'
const DANGER = '#c2410c'
const SUCCESS = '#15803d'
const SLICES = [AMBER, INK, SUCCESS, STEEL, DANGER, '#2a6f97', '#7b5ea7', '#4b525c']

const compact = new Intl.NumberFormat('en-IN', { notation: 'compact', maximumFractionDigits: 1 })
const rupees = (value: unknown) => formatPrice(Number(value).toFixed(2))

export function RevenueChart({ rows }: { rows: SeriesRow[] }) {
  const data = rows.map((row) => ({
    label: row.label,
    Orders: row.orders,
    Revenue: Number(row.revenue),
    Refunded: Number(row.refunded),
  }))
  return (
    <div className="h-72" aria-hidden>
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid stroke="#eceef1" vertical={false} />
          <XAxis dataKey="label" tick={{ fontSize: 11, fill: STEEL }} tickLine={false} minTickGap={16} />
          <YAxis
            yAxisId="money"
            tick={{ fontSize: 11, fill: STEEL }}
            tickLine={false}
            axisLine={false}
            width={48}
            tickFormatter={(value: number) => `₹${compact.format(value)}`}
          />
          <YAxis yAxisId="count" orientation="right" allowDecimals={false} tick={{ fontSize: 11, fill: STEEL }} tickLine={false} axisLine={false} width={32} />
          <Tooltip formatter={(value, name) => (name === 'Orders' ? String(value) : rupees(value))} />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          <Bar yAxisId="money" dataKey="Revenue" fill={AMBER} radius={[3, 3, 0, 0]} maxBarSize={28} />
          <Bar yAxisId="money" dataKey="Refunded" fill={DANGER} radius={[3, 3, 0, 0]} maxBarSize={28} />
          <Line yAxisId="count" dataKey="Orders" stroke={INK} strokeWidth={2} dot={false} />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  )
}

export function OrdersChart({ rows }: { rows: SeriesRow[] }) {
  const data = rows.map((row) => ({
    label: row.label,
    Delivered: row.delivered,
    Cancelled: row.cancelled,
    Other: Math.max(row.orders - row.delivered - row.cancelled, 0),
  }))
  return (
    <div className="h-64" aria-hidden>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid stroke="#eceef1" vertical={false} />
          <XAxis dataKey="label" tick={{ fontSize: 11, fill: STEEL }} tickLine={false} minTickGap={16} />
          <YAxis allowDecimals={false} tick={{ fontSize: 11, fill: STEEL }} tickLine={false} axisLine={false} width={32} />
          <Tooltip />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          <Bar dataKey="Delivered" stackId="orders" fill={SUCCESS} maxBarSize={28} />
          <Bar dataKey="Other" name="In progress" stackId="orders" fill={STEEL} maxBarSize={28} />
          <Bar dataKey="Cancelled" stackId="orders" fill={DANGER} maxBarSize={28} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

export function ShareChart({ rows }: { rows: { name: string; value: number }[] }) {
  return (
    <div className="h-64" aria-hidden>
      <ResponsiveContainer width="100%" height="100%">
        <PieChart>
          <Pie data={rows} dataKey="value" nameKey="name" innerRadius="45%" outerRadius="80%" paddingAngle={1}>
            {rows.map((row, index) => (
              <Cell key={row.name} fill={SLICES[index % SLICES.length]} />
            ))}
          </Pie>
          <Tooltip formatter={(value) => rupees(value)} />
          <Legend wrapperStyle={{ fontSize: 12 }} />
        </PieChart>
      </ResponsiveContainer>
    </div>
  )
}
