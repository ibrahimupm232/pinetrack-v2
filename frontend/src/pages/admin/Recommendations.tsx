import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Sprout } from 'lucide-react'
import AdminLayout from '../../components/layout/AdminLayout'
import PlotRecommendationCard from '../../components/soil/PlotRecommendationCard'
import { soilTypeLabel } from '../../components/soil/soilMeta'
import { apiClient, apiErrorMessage } from '../../services/api'
import { PlotOutcome, PlotRecommendation } from '../../types'
import { tr, locale } from '../../i18n'

const card = 'bg-white rounded-xl border border-gray-200 shadow-sm'
const GRADE_COLORS: Record<string, string> = { A: 'bg-green-600', B: 'bg-lime-500', C: 'bg-amber-500', D: 'bg-red-500' }

export default function Recommendations() {
  const [recs, setRecs] = useState<PlotRecommendation[] | null>(null)
  const [outcomes, setOutcomes] = useState<PlotOutcome[]>([])
  const [error, setError] = useState('')

  useEffect(() => {
    Promise.all([apiClient.getRecommendations(), apiClient.getPlotOutcomes()])
      .then(([r, o]) => { setRecs(r); setOutcomes(o) })
      .catch((e) => { setRecs([]); setError(apiErrorMessage(e, tr("Could not load recommendations."))) })
  }, [])

  return (
    <AdminLayout title={tr("Cultivation Recommendations")}
      subtitle={tr("Variety, fertiliser, irrigation and timing advice per plot, from cleaned soil and weather data")}>
      <div className="space-y-6">
        {error && <p role="alert" className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">{error}</p>}

        {recs === null ? <p className="text-sm text-gray-500">{tr("Loading…")}</p>
          : recs.length === 0 ? (
            <section className={`${card} px-6 py-12 text-center`}>
              <Sprout size={28} className="mx-auto text-gray-400" />
              <p className="mt-2 text-sm font-semibold text-gray-900">{tr("No recommendations yet")}</p>
              <p className="mt-1 text-sm text-gray-500">
                {tr("Recommendations use only cleaned data.")} <Link to="/data-quality" className="font-medium text-green-700 hover:underline">{tr("Run the data-quality check")}</Link>
              </p>
            </section>
          ) : (
            <>
              <section className={`${card} overflow-x-auto`}>
                <table className="min-w-full text-sm">
                  <thead className="bg-gray-50 text-xs text-gray-500">
                    <tr>
                      {[tr("Plot"), tr("Recommended"), tr("Suitability"), tr("Runner-up"), tr("Confidence"), tr("Readings"), tr("Newest")].map((h) => (
                        <th key={h} className="px-4 py-2.5 text-left font-semibold">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100">
                    {recs.map((r) => (
                      <tr key={r.plot_name}>
                        <td className="px-4 py-2.5 font-medium text-gray-900">{r.plot_name}</td>
                        <td className="px-4 py-2.5 font-semibold text-green-800">{r.recommended_variety}</td>
                        <td className="px-4 py-2.5 tabular-nums">{Math.round(r.varieties[0].score)}</td>
                        <td className="px-4 py-2.5 text-gray-600">{r.varieties[1]?.variety} <span className="tabular-nums text-xs">({Math.round(r.varieties[1]?.score ?? 0)})</span></td>
                        <td className="px-4 py-2.5 tabular-nums">{Math.round(r.confidence)}% <span className="text-xs text-gray-500">{tr(r.confidence_level)}</span></td>
                        <td className="px-4 py-2.5 tabular-nums">{r.readings_used}</td>
                        <td className="px-4 py-2.5 text-gray-600 whitespace-nowrap">{new Date(r.latest_reading).toLocaleDateString(locale)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </section>

              <div className="grid gap-4 md:grid-cols-2 2xl:grid-cols-3">
                {recs.map((r) => <PlotRecommendationCard key={r.plot_name} rec={r} />)}
              </div>
            </>
          )}

        <section className={card}>
          <div className="p-5 pb-3">
            <h2 className="text-sm font-semibold text-gray-900">{tr("Harvest outcomes by plot")}</h2>
            <p className="text-xs text-gray-500 mt-0.5">{tr("Grades and rejections from Post-Harvest Management, next to each plot's soil and weather conditions")}</p>
          </div>
          <div className="overflow-x-auto">
            <table className="min-w-full text-sm">
              <thead className="bg-gray-50 text-xs text-gray-500">
                <tr>
                  {[tr("Plot"), tr("Batches"), tr("Harvested"), tr("Rejection rate"), tr("Grades A–D"), tr("Soil"), 'pH', tr("Moisture"), tr("Temp.")].map((h) => (
                    <th key={h} className="px-4 py-2.5 text-left font-semibold">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {outcomes.length === 0 && <tr><td colSpan={9} className="px-4 py-6 text-center text-gray-500">{tr("No data yet.")}</td></tr>}
                {outcomes.map((o) => (
                  <tr key={o.plot_name}>
                    <td className="px-4 py-2.5 font-medium text-gray-900">{o.plot_name}</td>
                    <td className="px-4 py-2.5 tabular-nums">{o.batches}</td>
                    <td className="px-4 py-2.5 tabular-nums whitespace-nowrap">{o.harvested_kg.toLocaleString(locale)} kg</td>
                    <td className={`px-4 py-2.5 tabular-nums ${o.rejection_rate != null && o.rejection_rate > 10 ? 'text-red-700 font-semibold' : ''}`}>{o.rejection_rate != null ? `${o.rejection_rate}%` : '—'}</td>
                    <td className="px-4 py-2.5 min-w-[9rem]">
                      {Object.keys(o.grade_share).length ? (
                        <div className="flex h-2.5 w-full overflow-hidden rounded-full bg-gray-100" title={Object.entries(o.grade_share).map(([g, v]) => `${g}: ${v}%`).join(' · ')}>
                          {(['A', 'B', 'C', 'D'] as const).map((g) => <div key={g} className={GRADE_COLORS[g]} style={{ width: `${o.grade_share[g] ?? 0}%` }} />)}
                        </div>
                      ) : <span className="text-gray-400">—</span>}
                    </td>
                    <td className="px-4 py-2.5 text-gray-600">{o.conditions ? soilTypeLabel(o.conditions.soil_type) : <span className="text-xs text-gray-400">{tr("No soil data")}</span>}</td>
                    <td className="px-4 py-2.5 tabular-nums text-gray-600">{o.conditions?.ph ?? '—'}</td>
                    <td className="px-4 py-2.5 tabular-nums text-gray-600">{o.conditions?.moisture != null ? `${o.conditions.moisture}%` : '—'}</td>
                    <td className="px-4 py-2.5 tabular-nums text-gray-600">{o.conditions?.temperature != null ? `${o.conditions.temperature}°C` : '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      </div>
    </AdminLayout>
  )
}
