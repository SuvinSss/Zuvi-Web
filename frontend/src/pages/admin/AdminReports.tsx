import { useMutation, useQuery } from '@tanstack/react-query'
import { Download, RefreshCw } from 'lucide-react'
import { BarList, TrendChart } from '@/components/charts'
import { QueryBoundary, Section, useToast } from '@/components/kit'
import { Button, Card, PageHeader } from '@/components/ui'
import { errorMessage } from '@/lib/api'
import { formatDate, formatMoney } from '@/lib/format'
import { label, ORDER_STATUS } from '@/lib/labels'
import { adminDashboard, downloadOrdersCsv } from '@/services/ops'
import { KpiCard, PeriodPicker, usePeriod } from './dashboardParts'

export default function AdminReports() {
  const period = usePeriod()
  const toast = useToast()
  const { from, to, invalid } = period
  const q = useQuery({ queryKey: ['admin-dashboard', from, to], queryFn: () => adminDashboard({ from, to }), enabled: !invalid, placeholderData: (p) => p })
  const exportCsv = useMutation({ mutationFn: () => downloadOrdersCsv({ from, to }), onError: (e) => toast('error', errorMessage(e)), onSuccess: () => toast('success', 'Orders exported.') })
  const d = q.data
  const perf = d?.delivery_performance
  return (
    <>
      <PageHeader title="Analytics and reports" subtitle="Everything here is calculated from real orders, deliveries and customers."
        actions={<>
          <Button variant="secondary" icon={RefreshCw} loading={q.isFetching} onClick={() => void q.refetch()}>Refresh</Button>
          <Button icon={Download} loading={exportCsv.isPending} disabled={invalid} onClick={() => exportCsv.mutate()}>Export orders (CSV)</Button>
        </>} />
      <div className="mb-6"><PeriodPicker period={period} /></div>
      <QueryBoundary query={invalid ? { isPending: false, isError: false, refetch: () => undefined, error: null } : q} skeleton="cards">
        {d && (
          <div className="space-y-8">
            <p className="text-sm text-muted">{formatDate(d.range.from)} – {formatDate(d.range.to)} compared with {formatDate(d.range.previous.from)} – {formatDate(d.range.previous.to)}.</p>
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
              <KpiCard label="Orders placed" value={d.kpis.orders.value} kpi={d.kpis.orders} />
              <KpiCard label="Delivered order value" value={formatMoney(d.kpis.revenue.value)} kpi={d.kpis.revenue} />
              <KpiCard label="Cancelled orders" value={d.kpis.cancelled.value} kpi={d.kpis.cancelled} />
              <KpiCard label="New customers" value={d.kpis.new_customers.value} kpi={d.kpis.new_customers} />
            </div>
            <div className="grid gap-6 lg:grid-cols-2">
              <Card className="p-4"><Section title="Orders placed"><TrendChart title="Orders placed per day" points={d.series.map((s) => ({ label: s.date, value: s.orders }))} kind="bar" /></Section></Card>
              <Card className="p-4"><Section title="Delivered order value"><TrendChart title="Delivered order value per day" points={d.series.map((s) => ({ label: s.date, value: Number(s.revenue) }))} format={(n) => formatMoney(n)} /></Section></Card>
              <Card className="p-4"><Section title="Cancellations"><TrendChart title="Cancelled orders per day" color="var(--color-danger)" points={d.series.map((s) => ({ label: s.date, value: s.cancelled }))} kind="bar" /></Section></Card>
              <Card className="p-4"><Section title="Customer growth"><TrendChart title="New customers per day" points={d.series.map((s) => ({ label: s.date, value: s.new_customers }))} kind="bar" /></Section></Card>
              <Card className="p-4"><Section title="Deliveries completed"><TrendChart title="Deliveries completed per day" points={d.series.map((s) => ({ label: s.date, value: s.delivered }))} kind="bar" /></Section></Card>
              <Card className="p-4"><Section title="Failed delivery attempts"><TrendChart title="Failed delivery attempts per day" color="var(--color-warn)" points={d.series.map((s) => ({ label: s.date, value: s.failed_deliveries }))} kind="bar" /></Section></Card>
            </div>
            {perf && (
              <Section title="Delivery performance">
                <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
                  <KpiCard label="Deliveries created" value={perf.total} />
                  <KpiCard label="Success rate" value={perf.success_rate_percent === null ? 'Not enough data' : `${perf.success_rate_percent}%`} hint="Delivered ÷ (delivered + failed)" />
                  <KpiCard label="Average time" value={perf.average_minutes_assignment_to_delivery === null ? 'Not enough data' : `${perf.average_minutes_assignment_to_delivery} min`} hint="Partner assigned → delivered" />
                  <KpiCard label="Retried" value={perf.retried} hint={`${perf.failed} failed · ${perf.cancelled} cancelled`} />
                </div>
              </Section>
            )}
            <div className="grid gap-6 lg:grid-cols-3">
              <Card className="p-4"><Section title="Order status"><BarList rows={d.status_distribution.map((r) => ({ key: r.status, label: label(ORDER_STATUS, r.status), value: r.count }))} /></Section></Card>
              <Card className="p-4"><Section title="Top stores"><BarList empty="No delivered orders in this period." rows={d.top_stores.map((s) => ({ key: String(s.store_id), label: s.name, value: Number(s.revenue), display: formatMoney(s.revenue), hint: `${s.orders} orders` }))} /></Section></Card>
              <Card className="p-4"><Section title="Best-selling products"><BarList empty="No sales in this period." rows={d.best_products.map((p) => ({ key: `${p.product_id}-${p.name}`, label: p.name, value: Number(p.quantity), display: `${Number(p.quantity)} sold`, hint: formatMoney(p.revenue) }))} /></Section></Card>
            </div>
            <p className="text-xs text-muted">{d.notes.revenue}</p>
          </div>
        )}
      </QueryBoundary>
    </>
  )
}
