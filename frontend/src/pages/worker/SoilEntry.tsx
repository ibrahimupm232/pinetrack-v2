import { useCallback, useEffect, useState } from 'react'
import { AlertTriangle, CheckCircle2, ClipboardList, Leaf, Sprout, Trash2 } from 'lucide-react'
import WorkerLayout from '../../components/layout/WorkerLayout'
import {
  EmptyState, ErrorNote, ICON_STROKE, Section, Segmented, WorkerPage, inputCls, labelCls, primaryBtn, secondaryBtn,
} from '../../components/worker/ui'
import PlotRecommendationCard from '../../components/soil/PlotRecommendationCard'
import { ScoreBadge, SOIL_FIELDS, WEATHER_FIELDS, soilTypeLabel, todayIso } from '../../components/soil/soilMeta'
import { apiClient, apiErrorMessage } from '../../services/api'
import { PlotRecommendation, SoilNumericField, SoilReading } from '../../types'
import { tr, locale } from '../../i18n'

type Tab = 'record' | 'advice' | 'history'

/** Possible ranges, only to warn about likely typing mistakes; the value is still saved as entered */
const POSSIBLE: Partial<Record<SoilNumericField, [number, number]>> = {
  ph: [2, 10], moisture: [0, 100], humidity: [0, 100], temperature: [5, 45], rainfall: [0, 400],
  organic_matter: [0, 100], ec: [0, 20],
}

type Values = Record<SoilNumericField, string>
const EMPTY_VALUES = Object.fromEntries([...SOIL_FIELDS, ...WEATHER_FIELDS].map((f) => [f.key, ''])) as Values

export default function SoilEntry() {
  const [tab, setTab] = useState<Tab>('record')
  const [plots, setPlots] = useState<string[]>([])
  const [plot, setPlot] = useState('')
  const [date, setDate] = useState(todayIso())
  const [soilType, setSoilType] = useState<'' | 'peat' | 'mineral'>('')
  const [values, setValues] = useState<Values>({ ...EMPTY_VALUES })
  const [notes, setNotes] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [saved, setSaved] = useState<SoilReading | null>(null)

  const [recs, setRecs] = useState<PlotRecommendation[] | null>(null)
  const [history, setHistory] = useState<SoilReading[] | null>(null)

  useEffect(() => { apiClient.listSoilPlots().then(setPlots).catch(() => setPlots([])) }, [])

  const loadAdvice = useCallback(() => {
    apiClient.getRecommendations().then(setRecs).catch(() => setRecs([]))
  }, [])
  const loadHistory = useCallback(() => {
    apiClient.listSoilReadings({ mine: true, limit: 50 }).then((d) => setHistory(d.items)).catch(() => setHistory([]))
  }, [])

  useEffect(() => {
    if (tab === 'advice' && recs === null) loadAdvice()
    if (tab === 'history' && history === null) loadHistory()
  }, [tab, recs, history, loadAdvice, loadHistory])

  const warning = (key: SoilNumericField) => {
    const raw = values[key].trim()
    const range = POSSIBLE[key]
    if (!raw || !range) return ''
    const n = Number(raw)
    return Number.isFinite(n) && (n < range[0] || n > range[1]) ? tr("Unusual value. Please check it.") : ''
  }

  const filledCount = Object.values(values).filter((v) => v.trim() !== '').length + (soilType ? 1 : 0)

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!plot.trim()) return setError(tr("Choose or type the plot name."))
    if (filledCount === 0) return setError(tr("Enter at least one reading."))
    setError('')
    setSaving(true)
    try {
      const nums = Object.fromEntries(
        Object.entries(values).map(([k, v]) => [k, v.trim() === '' ? null : Number(v)]),
      )
      const r = await apiClient.createSoilReading({
        plot_name: plot, reading_date: date, source: 'manual', soil_type: soilType || null,
        notes: notes || undefined, ...nums,
      })
      setSaved(r)
      setHistory(null)
    } catch (err) {
      setError(apiErrorMessage(err, tr("Could not save the reading. Please try again.")))
    } finally {
      setSaving(false)
    }
  }

  const resetForm = () => {
    setSaved(null)
    setValues({ ...EMPTY_VALUES })
    setNotes('')
  }

  const remove = async (id: number) => {
    if (!window.confirm(tr("Delete this reading?"))) return
    try {
      await apiClient.deleteSoilReading(id)
      setHistory((h) => (h ?? []).filter((r) => r.id !== id))
    } catch (err) {
      window.alert(apiErrorMessage(err, tr("Could not delete the reading.")))
    }
  }

  const numberInput = (f: typeof SOIL_FIELDS[number]) => {
    const warn = warning(f.key)
    return (
      <div key={f.key}>
        <label htmlFor={`soil_${f.key}`} className={labelCls}>
          {f.label}{f.unit && <span className="font-normal text-gray-400"> ({f.unit})</span>}
        </label>
        <input id={`soil_${f.key}`} type="number" inputMode="decimal" step={f.step ?? 'any'} placeholder="—"
          value={values[f.key]} onChange={(e) => setValues((p) => ({ ...p, [f.key]: e.target.value }))}
          className={`${inputCls} tabular-nums ${warn ? 'border-amber-400' : ''}`} aria-describedby={warn ? `w_${f.key}` : undefined} />
        {warn ? <p id={`w_${f.key}`} className="mt-1 text-[11px] text-amber-700">{warn}</p>
          : f.hint ? <p className="mt-1 text-[11px] text-gray-400">{f.hint}</p> : null}
      </div>
    )
  }

  // ── Saved confirmation ──
  if (saved) {
    return (
      <WorkerLayout>
        <WorkerPage title={tr("Reading Saved")} narrow>
          <section className="rounded-xl border border-gray-200 bg-white p-5 text-center shadow-sm">
            <span className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-green-50 text-green-700">
              <CheckCircle2 size={26} strokeWidth={ICON_STROKE} />
            </span>
            <p className="text-sm text-gray-600">{tr("The soil and weather reading for {0} has been recorded.", saved.plot_name)}</p>
            <p className="mt-2 text-xs text-gray-500">{tr("The admin checks every reading for errors before it is used in recommendations.")}</p>
          </section>
          <div className="grid gap-2 sm:grid-cols-2">
            <button onClick={resetForm} className={primaryBtn}>{tr("Record Another")}</button>
            <button onClick={() => { resetForm(); setTab('advice') }} className={secondaryBtn}>{tr("View Plot Advice")}</button>
          </div>
        </WorkerPage>
      </WorkerLayout>
    )
  }

  return (
    <WorkerLayout>
      <WorkerPage title={tr("Soil & Weather")} subtitle={tr("Record readings and get advice for your plots")} narrow>
        <Segmented<Tab> label={tr("Soil and weather views")} value={tab} onChange={setTab}
          options={[
            { value: 'record', label: tr("Record") },
            { value: 'advice', label: tr("Advice") },
            { value: 'history', label: tr("My readings") },
          ]} />

        {tab === 'record' && (
          <form onSubmit={submit} className="space-y-5" noValidate>
            <Section title={tr("Where and when")}>
              <div className="grid gap-4 sm:grid-cols-2">
                <div>
                  <label htmlFor="soil_plot" className={labelCls}>{tr("Plot")} <span className="text-red-600">*</span></label>
                  <input id="soil_plot" list="soil_plot_list" value={plot} onChange={(e) => setPlot(e.target.value)}
                    placeholder={tr("e.g. Block A")} className={inputCls} autoComplete="off" />
                  <datalist id="soil_plot_list">{plots.map((p) => <option key={p} value={p} />)}</datalist>
                </div>
                <div>
                  <label htmlFor="soil_date" className={labelCls}>{tr("Reading date")}</label>
                  <input id="soil_date" type="date" value={date} max={todayIso()} onChange={(e) => setDate(e.target.value)} className={inputCls} />
                </div>
              </div>
            </Section>

            <Section title={tr("Soil")} description={tr("Fill in what you measured; leave the rest empty.")}>
              <div>
                <p className={labelCls}>{tr("Soil type")}</p>
                <div role="radiogroup" aria-label={tr("Soil type")} className="grid grid-cols-2 gap-2.5">
                  {(['peat', 'mineral'] as const).map((s) => (
                    <button key={s} type="button" role="radio" aria-checked={soilType === s}
                      onClick={() => setSoilType((cur) => (cur === s ? '' : s))}
                      className={`rounded-lg border px-3 py-3 text-sm font-semibold transition-colors ${
                        soilType === s ? 'border-green-700 bg-green-50 text-green-900 ring-1 ring-green-700' : 'border-gray-200 bg-white text-gray-700 hover:border-gray-300'
                      }`}>
                      {soilTypeLabel(s)}
                    </button>
                  ))}
                </div>
              </div>
              <div className="grid grid-cols-2 gap-4">
                {SOIL_FIELDS.map(numberInput)}
              </div>
            </Section>

            <Section title={tr("Weather")}>
              <div className="grid grid-cols-2 gap-4">
                {WEATHER_FIELDS.map(numberInput)}
              </div>
            </Section>

            <Section>
              <div>
                <label htmlFor="soil_notes" className={labelCls}>{tr("Notes")}</label>
                <textarea id="soil_notes" rows={2} value={notes} onChange={(e) => setNotes(e.target.value)}
                  placeholder={tr("Probe used, weather today, anything unusual")} className={`${inputCls} resize-none`} />
              </div>
            </Section>

            {error && <ErrorNote>{error}</ErrorNote>}
            <button type="submit" disabled={saving} className={`${primaryBtn} w-full`}>
              {saving ? tr("Saving…") : tr("Save Reading")}
            </button>
          </form>
        )}

        {tab === 'advice' && (
          recs === null ? <p className="text-sm text-gray-500">{tr("Loading…")}</p>
          : recs.length === 0 ? (
            <EmptyState icon={Sprout} title={tr("No advice yet")}
              body={tr("Advice appears after readings are recorded and checked by the admin.")} />
          ) : (
            <div className="space-y-4">
              {recs.map((r) => <PlotRecommendationCard key={r.plot_name} rec={r} />)}
            </div>
          )
        )}

        {tab === 'history' && (
          history === null ? <p className="text-sm text-gray-500">{tr("Loading…")}</p>
          : history.length === 0 ? (
            <EmptyState icon={ClipboardList} title={tr("No readings yet")} body={tr("Readings you record will appear here.")}
              action={<button onClick={() => setTab('record')} className={primaryBtn}>{tr("Record a Reading")}</button>} />
          ) : (
            <ul className="space-y-2.5">
              {history.map((r) => {
                const issues = r.quality?.flags.filter((f) => ['invalid', 'unreadable', 'outlier', 'duplicate'].includes(f.type)) ?? []
                return (
                  <li key={r.id} className="rounded-xl border border-gray-200 bg-white p-3.5 shadow-sm">
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5"><Leaf size={14} className="text-green-700" />{r.plot_name}</p>
                        <p className="text-xs text-gray-500">
                          {new Date(r.reading_date).toLocaleDateString(locale, { day: 'numeric', month: 'short', year: 'numeric' })}
                          {' · '}pH {r.ph ?? '—'} · {soilTypeLabel(r.soil_type)}
                          {r.moisture != null && ` · ${r.moisture}%`}
                        </p>
                      </div>
                      <div className="flex items-center gap-1.5 shrink-0">
                        {r.quality ? <ScoreBadge score={r.quality.score} usable={r.quality.usable} />
                          : <span className="text-[11px] text-gray-500">{tr("Awaiting check")}</span>}
                        <button onClick={() => remove(r.id)} aria-label={tr("Delete reading")}
                          className="rounded-md p-1.5 text-gray-400 hover:bg-red-50 hover:text-red-600"><Trash2 size={15} /></button>
                      </div>
                    </div>
                    {issues.length > 0 && (
                      <p className="mt-2 flex gap-1.5 text-xs text-amber-800">
                        <AlertTriangle size={14} className="shrink-0 mt-px" />
                        {issues.map((f) => f.detail).join(' · ')}
                      </p>
                    )}
                  </li>
                )
              })}
            </ul>
          )
        )}
      </WorkerPage>
    </WorkerLayout>
  )
}
