import { Fragment, useCallback, useEffect, useRef, useState } from 'react'
import { Download, FileUp, Search, Trash2 } from 'lucide-react'
import AdminLayout from '../../components/layout/AdminLayout'
import AppSelect from '../../components/ui/AppSelect'
import { FlagBadge, ScoreBadge, soilTypeLabel } from '../../components/soil/soilMeta'
import { apiClient, apiErrorMessage, saveBlob } from '../../services/api'
import { SoilReading } from '../../types'
import { tr, locale } from '../../i18n'

const card = 'bg-white rounded-xl border border-gray-200 shadow-sm'
const PAGE = 50
const fmt = (v: number | null | undefined) => (v == null ? '—' : v.toLocaleString(locale, { maximumFractionDigits: 2 }))

const COLUMNS: { key: keyof SoilReading; label: string }[] = [
  { key: 'ph', label: 'pH' }, { key: 'nitrogen', label: 'N' }, { key: 'phosphorus', label: 'P' }, { key: 'potassium', label: 'K' },
  { key: 'moisture', label: tr("Moist. %") }, { key: 'temperature', label: tr("Temp.") }, { key: 'rainfall', label: tr("Rain") },
  { key: 'humidity', label: tr("RH %") },
]

export default function SoilData() {
  const [items, setItems] = useState<SoilReading[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(0)
  const [plots, setPlots] = useState<string[]>([])
  const [plot, setPlot] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [expanded, setExpanded] = useState<number | null>(null)

  const [source, setSource] = useState<'csv' | 'sensor' | 'agency'>('csv')
  const [importing, setImporting] = useState(false)
  const [importMsg, setImportMsg] = useState<{ ok: boolean; text: string; details?: string[] } | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  const load = useCallback(() => {
    setLoading(true)
    apiClient.listSoilReadings({ plot: plot || undefined, skip: page * PAGE, limit: PAGE })
      .then((d) => { setItems(d.items); setTotal(d.total); setError('') })
      .catch((e) => setError(apiErrorMessage(e, tr("Could not load readings."))))
      .finally(() => setLoading(false))
  }, [plot, page])

  useEffect(load, [load])
  useEffect(() => { apiClient.listSoilPlots().then(setPlots).catch(() => {}) }, [])

  const onFile = async (file: File) => {
    setImporting(true)
    setImportMsg(null)
    try {
      const text = await file.text()
      const res = await apiClient.importSoilCsv(text, source)
      setImportMsg({
        ok: res.imported > 0,
        text: tr("Imported {0} reading(s). {1} row(s) skipped, {2} unreadable value(s) stored as missing.",
          res.imported, res.skipped.length, res.unreadable_values),
        details: res.skipped.slice(0, 8).map((s) => tr("Line {0}: {1}", s.line, tr(s.reason))),
      })
      setPage(0)
      load()
      apiClient.listSoilPlots().then(setPlots).catch(() => {})
    } catch (e) {
      setImportMsg({ ok: false, text: apiErrorMessage(e, tr("Import failed.")) })
    } finally {
      setImporting(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  const remove = async (id: number) => {
    if (!window.confirm(tr("Delete this reading? Run the data-quality check again afterwards."))) return
    try {
      await apiClient.deleteSoilReading(id)
      load()
    } catch (e) {
      window.alert(apiErrorMessage(e, tr("Could not delete the reading.")))
    }
  }

  return (
    <AdminLayout title={tr("Soil & Weather Data")}
      subtitle={tr("Raw readings from workers, sensors and agency records, stored exactly as received")}>
      <div className="space-y-6">
        <section className={`${card} p-5`}>
          <div className="flex flex-col lg:flex-row lg:items-end gap-4">
            <div className="flex-1">
              <h2 className="text-sm font-semibold text-gray-900">{tr("Import readings from a CSV file")}</h2>
              <p className="text-xs text-gray-500 mt-0.5">
                {tr("Columns: plot_name, reading_date (YYYY-MM-DD), then any of ph, nitrogen, phosphorus, potassium, ec, moisture, organic_matter, soil_type, temperature, rainfall, humidity, solar_radiation.")}
              </p>
            </div>
            <div className="w-full sm:w-44">
              <label htmlFor="import_source" className="block text-xs font-semibold text-gray-600 mb-1">{tr("Source")}</label>
              <AppSelect id="import_source" value={source} onChange={(v) => setSource(v as typeof source)}
                options={[
                  { value: 'csv', label: tr("CSV / spreadsheet") },
                  { value: 'sensor', label: tr("Field sensor log") },
                  { value: 'agency', label: tr("Agency records") },
                ]} />
            </div>
            <div className="flex gap-2">
              <button type="button" onClick={async () => saveBlob(await apiClient.downloadSoilTemplate(), 'soil_weather_template.csv')}
                className="inline-flex items-center gap-2 rounded-lg border border-gray-200 bg-white px-3.5 py-2.5 text-sm font-medium text-gray-700 hover:bg-gray-50">
                <Download size={16} /> {tr("Template")}
              </button>
              <button type="button" disabled={importing} onClick={() => fileRef.current?.click()}
                className="inline-flex items-center gap-2 rounded-lg bg-green-700 px-3.5 py-2.5 text-sm font-semibold text-white hover:bg-green-800 disabled:opacity-60">
                <FileUp size={16} /> {importing ? tr("Importing…") : tr("Choose CSV")}
              </button>
              <input ref={fileRef} type="file" accept=".csv,text/csv" className="hidden"
                onChange={(e) => e.target.files?.[0] && onFile(e.target.files[0])} />
            </div>
          </div>
          {importMsg && (
            <div role="status" className={`mt-4 rounded-lg border px-4 py-3 text-sm ${importMsg.ok ? 'border-green-200 bg-green-50 text-green-900' : 'border-red-200 bg-red-50 text-red-800'}`}>
              {importMsg.text}
              {!!importMsg.details?.length && <ul className="mt-1 list-disc pl-5 text-xs">{importMsg.details.map((d) => <li key={d}>{d}</li>)}</ul>}
            </div>
          )}
        </section>

        <section className={card}>
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 p-4 border-b border-gray-100">
            <h2 className="text-sm font-semibold text-gray-900">{tr("{0} reading(s)", total)}</h2>
            <div className="w-full sm:w-56">
              <AppSelect value={plot} onChange={(v) => { setPlot(v); setPage(0) }} aria-label={tr("Filter by plot")}
                options={[{ value: '', label: tr("All plots") }, ...plots.map((p) => ({ value: p, label: p }))]} />
            </div>
          </div>

          {error && <p className="m-4 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">{error}</p>}

          <div className="overflow-x-auto">
            <table className="min-w-full text-sm">
              <thead className="bg-gray-50 text-xs text-gray-500">
                <tr>
                  <th className="px-4 py-2.5 text-left font-semibold">{tr("Plot")}</th>
                  <th className="px-3 py-2.5 text-left font-semibold">{tr("Date")}</th>
                  <th className="px-3 py-2.5 text-left font-semibold">{tr("Soil")}</th>
                  {COLUMNS.map((c) => <th key={c.key} className="px-3 py-2.5 text-right font-semibold">{c.label}</th>)}
                  <th className="px-3 py-2.5 text-left font-semibold">{tr("Source")}</th>
                  <th className="px-3 py-2.5 text-left font-semibold">{tr("Quality")}</th>
                  <th className="px-3 py-2.5" />
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {loading && <tr><td colSpan={14} className="px-4 py-8 text-center text-gray-500">{tr("Loading…")}</td></tr>}
                {!loading && items.length === 0 && (
                  <tr><td colSpan={14} className="px-4 py-10 text-center text-gray-500">
                    <Search size={20} className="mx-auto mb-2 text-gray-400" />
                    {tr("No readings yet. Workers can record them from the Soil tab, or import a CSV above.")}
                  </td></tr>
                )}
                {!loading && items.map((r) => {
                  const flags = r.quality?.flags ?? []
                  return (
                    <Fragment key={r.id}>
                      <tr className="hover:bg-gray-50 cursor-pointer" onClick={() => setExpanded(expanded === r.id ? null : r.id)}>
                        <td className="px-4 py-2.5 font-medium text-gray-900 whitespace-nowrap">{r.plot_name}</td>
                        <td className="px-3 py-2.5 whitespace-nowrap text-gray-600">{new Date(r.reading_date).toLocaleDateString(locale, { day: 'numeric', month: 'short', year: '2-digit' })}</td>
                        <td className="px-3 py-2.5 text-gray-600">{r.soil_type ?? '—'}</td>
                        {COLUMNS.map((c) => <td key={c.key} className="px-3 py-2.5 text-right tabular-nums text-gray-700">{fmt(r[c.key] as number | null)}</td>)}
                        <td className="px-3 py-2.5 text-gray-600 whitespace-nowrap">{tr(r.source)}{r.recorded_by ? ` · ${r.recorded_by}` : ''}</td>
                        <td className="px-3 py-2.5 whitespace-nowrap">
                          {r.quality ? <span className="inline-flex items-center gap-1.5"><ScoreBadge score={r.quality.score} usable={r.quality.usable} />
                            {flags.length > 0 && <span className="text-[11px] text-gray-500">{tr("{0} flag(s)", flags.length)}</span>}</span>
                            : <span className="text-[11px] text-gray-500">{tr("Not checked")}</span>}
                        </td>
                        <td className="px-3 py-2.5 text-right">
                          <button onClick={(e) => { e.stopPropagation(); remove(r.id) }} aria-label={tr("Delete reading")}
                            className="rounded-md p-1.5 text-gray-400 hover:bg-red-50 hover:text-red-600"><Trash2 size={15} /></button>
                        </td>
                      </tr>
                      {expanded === r.id && (
                        <tr className="bg-gray-50/60">
                          <td colSpan={14} className="px-4 py-3">
                            {flags.length === 0 ? <p className="text-xs text-gray-500">{r.quality ? tr("No issues found in this reading.") : tr("Run the data-quality check to inspect this reading.")}</p> : (
                              <ul className="space-y-1">
                                {flags.map((f, i) => (
                                  <li key={i} className="flex items-start gap-2 text-xs text-gray-700"><FlagBadge type={f.type} /><span className="pt-0.5">{f.detail}</span></li>
                                ))}
                              </ul>
                            )}
                            {r.quality && (
                              <p className="mt-2 text-[11px] text-gray-500">
                                {tr("Cleaned")}: pH {fmt(r.quality.cleaned.ph)} · {tr("Temp.")} {fmt(r.quality.cleaned.temperature)} °C · {tr("Moist.")} {fmt(r.quality.cleaned.moisture)}% · {soilTypeLabel(r.quality.cleaned.soil_type)}
                              </p>
                            )}
                            {r.notes && <p className="mt-1 text-[11px] text-gray-500">{tr("Notes")}: {r.notes}</p>}
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  )
                })}
              </tbody>
            </table>
          </div>

          {total > PAGE && (
            <div className="flex items-center justify-between p-4 border-t border-gray-100 text-sm">
              <button disabled={page === 0} onClick={() => setPage((p) => p - 1)} className="rounded-lg border border-gray-200 px-3 py-1.5 disabled:opacity-40">{tr("Previous")}</button>
              <span className="text-gray-500">{tr("Page {0} of {1}", page + 1, Math.ceil(total / PAGE))}</span>
              <button disabled={(page + 1) * PAGE >= total} onClick={() => setPage((p) => p + 1)} className="rounded-lg border border-gray-200 px-3 py-1.5 disabled:opacity-40">{tr("Next")}</button>
            </div>
          )}
        </section>
      </div>
    </AdminLayout>
  )
}
