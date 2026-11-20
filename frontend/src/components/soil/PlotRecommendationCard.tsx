import { useState } from 'react'
import { CalendarClock, ChevronDown, Droplets, FlaskConical, Info, Sprout } from 'lucide-react'
import { PlotRecommendation } from '../../types'
import { ConfidenceBadge, soilTypeLabel } from './soilMeta'
import { tr, locale } from '../../i18n'

function Tips({ icon: Icon, title, items }: { icon: React.ElementType; title: string; items: string[] }) {
  return (
    <div>
      <p className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-gray-500">
        <Icon size={14} strokeWidth={1.75} /> {title}
      </p>
      <ul className="mt-1.5 space-y-1.5">
        {items.map((t) => (
          <li key={t} className="text-sm leading-snug text-gray-700 pl-3 relative before:absolute before:left-0 before:top-2 before:h-1 before:w-1 before:rounded-full before:bg-green-600">
            {tr(t)}
          </li>
        ))}
      </ul>
    </div>
  )
}

/** One plot's recommendation: the farmer's view, also used on the admin page */
export default function PlotRecommendationCard({ rec, defaultOpen = false }: { rec: PlotRecommendation; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen)
  const best = rec.varieties[0]
  const c = rec.conditions
  const facts = [
    [tr("Soil"), soilTypeLabel(c.soil_type)],
    [tr("pH"), c.ph ?? '—'],
    [tr("Moisture"), c.moisture != null ? `${c.moisture}%` : '—'],
    [tr("Temp."), c.temperature != null ? `${c.temperature}°C` : '—'],
  ]

  return (
    <article className="rounded-xl border border-gray-200 bg-white shadow-sm">
      <div className="p-4 sm:p-5">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div className="min-w-0">
            <p className="text-xs font-medium text-gray-500">{rec.plot_name}</p>
            <h3 className="mt-0.5 flex items-center gap-2 text-lg font-bold text-gray-900">
              <Sprout size={18} strokeWidth={1.75} className="text-green-700" />
              {tr("Plant {0}", rec.recommended_variety)}
            </h3>
            <p className="text-xs text-gray-500 mt-0.5">{tr("Suitability {0}/100", Math.round(best.score))}</p>
          </div>
          <ConfidenceBadge level={rec.confidence_level} value={rec.confidence} />
        </div>

        <dl className="mt-3 grid grid-cols-4 gap-2 rounded-lg bg-gray-50 p-2.5 text-center">
          {facts.map(([k, v]) => (
            <div key={String(k)} className="min-w-0">
              <dt className="text-[10px] uppercase tracking-wide text-gray-500">{k}</dt>
              <dd className="truncate text-sm font-semibold tabular-nums text-gray-900">{v}</dd>
            </div>
          ))}
        </dl>

        {rec.notes.length > 0 && (
          <div className="mt-3 space-y-1">
            {rec.notes.map((n) => (
              <p key={n} className="flex gap-1.5 text-xs text-amber-800"><Info size={14} className="shrink-0 mt-px" />{tr(n)}</p>
            ))}
          </div>
        )}

        <div className="mt-4 space-y-4">
          <Tips icon={FlaskConical} title={tr("Fertiliser")} items={rec.fertiliser} />
          <Tips icon={Droplets} title={tr("Irrigation")} items={rec.irrigation} />
          <Tips icon={CalendarClock} title={tr("Flowering & harvest")} items={rec.timing} />
        </div>
      </div>

      <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open}
        className="flex w-full items-center justify-between border-t border-gray-100 px-4 sm:px-5 py-3 text-sm font-medium text-gray-700 hover:bg-gray-50 rounded-b-xl">
        {tr("Why this variety?")}
        <ChevronDown size={16} className={`transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>
      {open && (
        <div className="border-t border-gray-100 px-4 sm:px-5 py-4 space-y-4">
          {rec.varieties.map((v) => (
            <div key={v.variety}>
              <div className="flex items-baseline justify-between gap-2">
                <p className="text-sm font-semibold text-gray-900">{v.variety}</p>
                <p className="text-sm tabular-nums font-semibold text-gray-700">{Math.round(v.score)}</p>
              </div>
              <div className="mt-1 h-2 rounded-full bg-gray-100">
                <div className={`h-2 rounded-full ${v.variety === best.variety ? 'bg-green-600' : 'bg-gray-400'}`} style={{ width: `${v.score}%` }} />
              </div>
              <p className="mt-1 text-xs text-gray-500">{tr(v.description)}</p>
              <div className="mt-1.5 flex flex-wrap gap-1.5">
                {v.factors.map((f) => (
                  <span key={f.factor} className={`rounded-md px-1.5 py-0.5 text-[11px] ${f.fit >= 80 ? 'bg-green-50 text-green-800' : f.fit >= 40 ? 'bg-amber-50 text-amber-800' : 'bg-red-50 text-red-800'}`}>
                    {tr(f.factor)}: {String(f.value)} ({tr("prefers {0}", f.preferred)})
                  </span>
                ))}
              </div>
            </div>
          ))}
          <p className="text-[11px] text-gray-400">
            {tr("Based on {0} cleaned reading(s), newest {1}.", rec.readings_used,
              new Date(rec.latest_reading).toLocaleDateString(locale, { day: 'numeric', month: 'short', year: 'numeric' }))}
          </p>
        </div>
      )}
    </article>
  )
}
