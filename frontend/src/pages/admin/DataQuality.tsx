import { useCallback, useEffect, useState } from 'react'
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import {
  AlertTriangle, ArrowRight, CheckCircle2, Copy, Download, Eraser, Gauge, ListChecks, Play, Ruler, ScanSearch, Sigma,
} from 'lucide-react'
import AdminLayout from '../../components/layout/AdminLayout'
import AppSelect from '../../components/ui/AppSelect'
import { DIMENSIONS, FlagBadge, FLAG_META, fieldLabel, scoreBg, scoreTone } from '../../components/soil/soilMeta'
import { apiClient, apiErrorMessage, saveBlob } from '../../services/api'
import { PlotQuality, QualityFlagType, QualityIssue, QualityLatest, QualityRun, RecommendationImpact } from '../../types'
import { tr, locale } from '../../i18n'

const card = 'bg-white rounded-xl border border-gray-200 shadow-sm'
type Method = QualityRun['imputation_method']

const METHODS: { value: Method; label: string }[] = [
  { value: 'median', label: tr("Median (robust, default)") },
  { value: 'mean', label: tr("Mean") },
  { value: 'knn', label: tr("k-nearest neighbours (k=3)") },
]

const dt = (iso: string) => new Date(iso).toLocaleString(locale, { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' })

function Kpi({ label, value, sub, tone }: { label: string; value: React.ReactNode; sub?: string; tone?: string }) {
  return (
    <div className={`${card} px-4 py-3.5`}>
      <p className="text-xs font-medium text-gray-500">{label}</p>
      <p className={`mt-1 text-2xl font-bold tabular-nums ${tone ?? 'text-gray-900'}`}>{value}</p>
      {sub && <p className="text-[11px] text-gray-500 mt-0.5">{sub}</p>}
    </div>
  )
}

export default function DataQuality() {
  const [latest, setLatest] = useState<QualityLatest | null>(null)
  const [plots, setPlots] = useState<PlotQuality[]>([])
  const [issues, setIssues] = useState<QualityIssue[]>([])
  const [issueType, setIssueType] = useState<'' | QualityFlagType>('')
  const [runs, setRuns] = useState<QualityRun[]>([])
  const [impact, setImpact] = useState<RecommendationImpact | null>(null)
  const [method, setMethod] = useState<Method>('median')
  const [running, setRunning] = useState(false)
  const [error, setError] = useState('')

  const loadAll = useCallback(async () => {
    try {
      const [l, p, r, imp] = await Promise.all([
        apiClient.getQualityLatest(), apiClient.getPlotQuality(), apiClient.listQualityRuns(), apiClient.getRecommendationImpact(),
      ])
      setLatest(l); setPlots(p); setRuns(r); setImpact(imp)
      if (l.run) setMethod(l.run.imputation_method)
    } catch (e) {
      setError(apiErrorMessage(e, tr("Could not load data-quality results.")))
    }
  }, [])

  useEffect(() => { loadAll() }, [loadAll])
  useEffect(() => {
    apiClient.getQualityIssues(issueType || undefined).then(setIssues).catch(() => setIssues([]))
  }, [issueType, latest?.run?.id])

  const run = async () => {
    setRunning(true)
    setError('')
    try {
      await apiClient.runDataQuality(method)
      await loadAll()
    } catch (e) {
      setError(apiErrorMessage(e, tr("The data-quality check failed.")))
    } finally {
      setRunning(false)
    }
  }

  const r = latest?.run ?? null
  const chartData = r ? DIMENSIONS.map((d) => ({ name: d.label, [tr("Raw")]: r.metrics_before[d.key], [tr("Cleaned")]: r.metrics_after[d.key] })) : []

  const stages = r ? [
    { icon: ScanSearch, title: tr("1. Profile"),   text: tr("{0} records, {1} plots", r.records_processed, r.profile?.plots ?? '—') },
    { icon: Eraser,     title: tr("2. Clean"),     text: tr("{0} corrected, {1} invalid removed, {2} duplicates", r.corrections_made, r.invalid_values, r.duplicates_removed) },
    { icon: Copy,       title: tr("3. Missing"),   text: tr("{0} values imputed ({1})", r.values_imputed, r.imputation_method) },
    { icon: AlertTriangle, title: tr("4. Outliers"), text: tr("{0} flagged (IQR), kept", r.outliers_flagged) },
    { icon: Ruler,      title: tr("5. Normalise"), text: tr("Min–max 0–1") },
    { icon: ListChecks, title: tr("6. Validate & score"), text: tr("Score {0} → {1}", r.score_before, r.score_after) },
  ] : []

  return (
    <AdminLayout title={tr("Data Quality")}
      subtitle={tr("Six-stage pipeline that checks soil and weather data before it reaches the recommendation engine")}
      actions={
        <>
          <button type="button" disabled={!r} onClick={async () => saveBlob(await apiClient.downloadQualityReport(), 'data_quality_report.csv')}
            className="inline-flex items-center gap-2 rounded-lg border border-gray-200 bg-white px-3.5 py-2.5 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50">
            <Download size={16} /> {tr("Report")}
          </button>
        </>
      }>
      <div className="space-y-6">
        {/* Run control */}
        <section className={`${card} p-5 flex flex-col lg:flex-row lg:items-end gap-4`}>
          <div className="flex-1 min-w-0">
            <h2 className="text-sm font-semibold text-gray-900">{tr("Run the data-quality check")}</h2>
            <p className="text-xs text-gray-500 mt-0.5">
              {latest ? tr("{0} reading(s) stored, {1} not yet checked.", latest.total_readings, latest.unprocessed_readings) : tr("Loading…")}
              {r && ` ${tr("Last run {0}.", dt(r.created_at))}`}
            </p>
          </div>
          <div className="w-full sm:w-64">
            <label htmlFor="dq_method" className="block text-xs font-semibold text-gray-600 mb-1">{tr("Missing-value method")}</label>
            <AppSelect id="dq_method" value={method} onChange={(v) => setMethod(v as Method)} options={METHODS} />
          </div>
          <button type="button" onClick={run} disabled={running || !latest?.total_readings}
            className="inline-flex items-center justify-center gap-2 rounded-lg bg-green-700 px-4 py-2.5 text-sm font-semibold text-white hover:bg-green-800 disabled:opacity-60">
            <Play size={16} /> {running ? tr("Running…") : tr("Run pipeline")}
          </button>
        </section>

        {error && <p role="alert" className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">{error}</p>}
        {latest && latest.unprocessed_readings > 0 && r && (
          <p className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
            {tr("{0} new reading(s) since the last run. Run the pipeline again so recommendations use them.", latest.unprocessed_readings)}
          </p>
        )}

        {!r ? (
          latest && (
            <section className={`${card} px-6 py-12 text-center`}>
              <Gauge size={28} className="mx-auto text-gray-400" />
              <p className="mt-2 text-sm font-semibold text-gray-900">{tr("No data-quality run yet")}</p>
              <p className="mt-1 text-sm text-gray-500">{latest.total_readings ? tr("Run the pipeline to profile, clean and score the readings.") : tr("Record or import soil and weather readings first.")}</p>
            </section>
          )
        ) : (
          <>
            {/* Headline */}
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
              <div className={`${card} px-4 py-3.5 col-span-2`}>
                <p className="text-xs font-medium text-gray-500">{tr("Overall data-quality score")}</p>
                <div className="mt-1 flex items-center gap-3">
                  <span className={`text-3xl font-bold tabular-nums ${scoreTone(r.score_before)}`}>{r.score_before}</span>
                  <ArrowRight size={20} className="text-gray-400" />
                  <span className={`text-3xl font-bold tabular-nums ${scoreTone(r.score_after)}`}>{r.score_after}</span>
                  <span className="ml-1 rounded-full bg-green-50 px-2 py-0.5 text-xs font-semibold text-green-800 ring-1 ring-green-200">
                    {r.score_after - r.score_before >= 0 ? '+' : ''}{(r.score_after - r.score_before).toFixed(1)}
                  </span>
                </div>
                <p className="text-[11px] text-gray-500 mt-1">{tr("Raw data → cleaned data (weighted DAMA dimensions)")}</p>
              </div>
              <Kpi label={tr("Records processed")} value={r.records_processed} sub={tr("{0} duplicates set aside", r.duplicates_removed)} />
              <Kpi label={tr("Values fixed")} value={r.corrections_made + r.values_imputed}
                sub={tr("{0} corrected · {1} imputed", r.corrections_made, r.values_imputed)} />
            </div>

            {/* Pipeline stages */}
            <section className={`${card} p-5`}>
              <h2 className="text-sm font-semibold text-gray-900 mb-4">{tr("Pipeline stages (last run)")}</h2>
              <ol className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
                {stages.map(({ icon: Icon, title, text }) => (
                  <li key={title} className="rounded-lg border border-gray-200 bg-gray-50/60 p-3">
                    <p className="flex items-center gap-2 text-sm font-semibold text-gray-900"><Icon size={16} className="text-green-700" />{title}</p>
                    <p className="mt-1 text-xs text-gray-600">{text}</p>
                  </li>
                ))}
              </ol>
            </section>

            {/* Before / after */}
            <div className="grid gap-6 xl:grid-cols-5">
              <section className={`${card} p-5 xl:col-span-3`}>
                <h2 className="text-sm font-semibold text-gray-900">{tr("Quality dimensions: raw vs cleaned")}</h2>
                <p className="text-xs text-gray-500 mt-0.5">{tr("Percent, higher is better")}</p>
                <div className="mt-4 h-72">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={chartData} margin={{ top: 4, right: 8, left: -16, bottom: 0 }} barGap={2}>
                      <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e5e7eb" />
                      <XAxis dataKey="name" tick={{ fontSize: 11, fill: '#6b7280' }} interval={0} />
                      <YAxis domain={[0, 100]} tick={{ fontSize: 11, fill: '#6b7280' }} />
                      <Tooltip formatter={(v: number) => `${v}%`} />
                      <Legend wrapperStyle={{ fontSize: 12 }} />
                      <Bar dataKey={tr("Raw")} fill="#d1a26b" radius={[3, 3, 0, 0]} />
                      <Bar dataKey={tr("Cleaned")} fill="#15803d" radius={[3, 3, 0, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </section>
              <section className={`${card} p-5 xl:col-span-2`}>
                <h2 className="text-sm font-semibold text-gray-900 mb-3">{tr("What each dimension measures")}</h2>
                <table className="w-full text-sm">
                  <thead className="text-xs text-gray-500"><tr><th className="text-left font-semibold pb-2">{tr("Dimension")}</th><th className="text-right font-semibold pb-2">{tr("Raw")}</th><th className="text-right font-semibold pb-2">{tr("Cleaned")}</th></tr></thead>
                  <tbody className="divide-y divide-gray-100">
                    {DIMENSIONS.map((d) => (
                      <tr key={d.key}>
                        <td className="py-2 pr-2"><p className="font-medium text-gray-900">{d.label}</p><p className="text-[11px] text-gray-500">{d.desc}</p></td>
                        <td className="py-2 text-right tabular-nums text-gray-600">{r.metrics_before[d.key]}%</td>
                        <td className={`py-2 text-right tabular-nums font-semibold ${scoreTone(r.metrics_after[d.key])}`}>{r.metrics_after[d.key]}%</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </section>
            </div>

            {/* Profile */}
            {r.profile && (
              <section className={card}>
                <div className="p-5 pb-3"><h2 className="text-sm font-semibold text-gray-900 flex items-center gap-2"><Sigma size={16} className="text-green-700" />{tr("Stage 1: raw data profile")}</h2></div>
                <div className="overflow-x-auto">
                  <table className="min-w-full text-sm">
                    <thead className="bg-gray-50 text-xs text-gray-500">
                      <tr>
                        {[tr("Field"), tr("Present"), tr("Missing"), tr("Out of range"), tr("Min"), tr("Mean"), tr("Max")].map((h, i) => (
                          <th key={h} className={`px-4 py-2.5 font-semibold ${i ? 'text-right' : 'text-left'}`}>{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-100">
                      {Object.entries(r.profile.fields).map(([k, f]) => (
                        <tr key={k}>
                          <td className="px-4 py-2 text-gray-900">{fieldLabel(k)} {f.unit && <span className="text-gray-400 text-xs">({f.unit})</span>}</td>
                          <td className="px-4 py-2 text-right tabular-nums">{f.present}</td>
                          <td className={`px-4 py-2 text-right tabular-nums ${f.missing ? 'text-amber-700 font-medium' : ''}`}>{f.missing}</td>
                          <td className={`px-4 py-2 text-right tabular-nums ${(f.out_of_range ?? f.unrecognised ?? 0) ? 'text-red-700 font-medium' : ''}`}>{f.out_of_range ?? f.unrecognised ?? 0}</td>
                          <td className="px-4 py-2 text-right tabular-nums text-gray-600">{f.min ?? '—'}</td>
                          <td className="px-4 py-2 text-right tabular-nums text-gray-600">{f.mean ?? '—'}</td>
                          <td className="px-4 py-2 text-right tabular-nums text-gray-600">{f.max ?? '—'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
            )}

            <div className="grid gap-6 xl:grid-cols-2">
              {/* Plot quality */}
              <section className={card}>
                <div className="p-5 pb-3"><h2 className="text-sm font-semibold text-gray-900">{tr("Quality by plot")}</h2></div>
                <ul className="divide-y divide-gray-100">
                  {plots.map((p) => (
                    <li key={p.plot_name} className="px-5 py-3">
                      <div className="flex items-center justify-between gap-3">
                        <p className="text-sm font-medium text-gray-900">{p.plot_name}</p>
                        <p className={`text-sm font-bold tabular-nums ${scoreTone(p.avg_score)}`}>{p.avg_score}</p>
                      </div>
                      <div className="mt-1.5 h-1.5 rounded-full bg-gray-100"><div className={`h-1.5 rounded-full ${scoreBg(p.avg_score)}`} style={{ width: `${p.avg_score}%` }} /></div>
                      <p className="mt-1 text-[11px] text-gray-500">
                        {tr("{0}/{1} usable · {2} imputed · {3} outliers · {4} invalid", p.usable, p.readings, p.imputed, p.outliers, p.invalid)}
                      </p>
                    </li>
                  ))}
                </ul>
              </section>

              {/* Raw vs cleaned recommendations (O3) */}
              <section className={card}>
                <div className="p-5 pb-3">
                  <h2 className="text-sm font-semibold text-gray-900">{tr("Effect on recommendations")}</h2>
                  <p className="text-xs text-gray-500 mt-0.5">
                    {impact ? tr("Variety recommended from raw data vs cleaned data. {0} plot(s) change.", impact.changed) : ''}
                  </p>
                </div>
                <div className="overflow-x-auto">
                  <table className="min-w-full text-sm">
                    <thead className="bg-gray-50 text-xs text-gray-500">
                      <tr>
                        <th className="px-4 py-2.5 text-left font-semibold">{tr("Plot")}</th>
                        <th className="px-4 py-2.5 text-left font-semibold">{tr("Raw data")}</th>
                        <th className="px-4 py-2.5 text-left font-semibold">{tr("Cleaned data")}</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-100">
                      {impact?.plots.map((p) => (
                        <tr key={p.plot_name} className={p.changed ? 'bg-amber-50/50' : ''}>
                          <td className="px-4 py-2.5 font-medium text-gray-900">{p.plot_name}</td>
                          <td className="px-4 py-2.5 text-gray-700">
                            {p.raw_variety} <span className="text-xs text-gray-500 tabular-nums">({Math.round(p.raw_score)})</span>
                            <p className="text-[11px] text-gray-500">pH {p.raw_conditions.ph ?? '—'} · {p.raw_conditions.temperature ?? '—'}° · {p.raw_conditions.soil_type ?? '—'}</p>
                          </td>
                          <td className="px-4 py-2.5 text-gray-700">
                            {p.clean_variety ? <>{p.clean_variety} <span className="text-xs text-gray-500 tabular-nums">({Math.round(p.clean_score ?? 0)})</span>
                              {p.changed && <span className="ml-1.5 rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-semibold text-amber-900">{tr("changed")}</span>}
                              <p className="text-[11px] text-gray-500">pH {p.clean_conditions?.ph ?? '—'} · {p.clean_conditions?.temperature ?? '—'}° · {p.clean_conditions?.soil_type ?? '—'}</p></>
                              : <span className="text-xs text-gray-500">{tr("No usable data")}</span>}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
            </div>

            {/* Issues */}
            <section className={card}>
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 p-5 pb-3">
                <h2 className="text-sm font-semibold text-gray-900">{tr("Processing decisions ({0})", issues.length)}</h2>
                <div className="w-full sm:w-52">
                  <AppSelect value={issueType} onChange={(v) => setIssueType(v as typeof issueType)} aria-label={tr("Filter by type")}
                    options={[{ value: '', label: tr("All types") }, ...(Object.keys(FLAG_META) as QualityFlagType[]).map((t) => ({ value: t, label: FLAG_META[t].label }))]} />
                </div>
              </div>
              {issues.length === 0 ? (
                <p className="px-5 pb-5 text-sm text-gray-500 flex items-center gap-2"><CheckCircle2 size={16} className="text-green-600" />{tr("Nothing of this type.")}</p>
              ) : (
                <ul className="max-h-[28rem] overflow-y-auto divide-y divide-gray-100">
                  {issues.map((i, n) => (
                    <li key={n} className="flex flex-wrap items-start gap-x-3 gap-y-1 px-5 py-2.5 text-sm">
                      <FlagBadge type={i.type} />
                      <span className="font-medium text-gray-900">{i.plot_name}</span>
                      <span className="text-gray-500 text-xs pt-0.5">{new Date(i.reading_date).toLocaleDateString(locale)} · {fieldLabel(i.field)}</span>
                      <span className="basis-full text-xs text-gray-600">{i.detail}</span>
                    </li>
                  ))}
                </ul>
              )}
            </section>

            <div className="grid gap-6 xl:grid-cols-2">
              <section className={`${card} p-5`}>
                <h2 className="text-sm font-semibold text-gray-900 mb-3">{tr("Processing log (last run)")}</h2>
                <ol className="space-y-2 text-sm text-gray-700 list-decimal pl-5">{(r.log ?? []).map((l) => <li key={l}>{l}</li>)}</ol>
              </section>
              <section className={card}>
                <div className="p-5 pb-3"><h2 className="text-sm font-semibold text-gray-900">{tr("Run history")}</h2></div>
                <table className="min-w-full text-sm">
                  <thead className="bg-gray-50 text-xs text-gray-500">
                    <tr><th className="px-5 py-2 text-left font-semibold">{tr("When")}</th><th className="px-3 py-2 text-left font-semibold">{tr("Method")}</th><th className="px-3 py-2 text-right font-semibold">{tr("Records")}</th><th className="px-5 py-2 text-right font-semibold">{tr("Score")}</th></tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100">
                    {runs.map((x) => (
                      <tr key={x.id}>
                        <td className="px-5 py-2 text-gray-700 whitespace-nowrap">{dt(x.created_at)}</td>
                        <td className="px-3 py-2 text-gray-600">{x.imputation_method}</td>
                        <td className="px-3 py-2 text-right tabular-nums">{x.records_processed}</td>
                        <td className="px-5 py-2 text-right tabular-nums whitespace-nowrap">{x.score_before} → <span className={`font-semibold ${scoreTone(x.score_after)}`}>{x.score_after}</span></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </section>
            </div>
          </>
        )}
      </div>
    </AdminLayout>
  )
}
