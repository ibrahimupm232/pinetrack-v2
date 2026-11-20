import { tr } from '../../i18n'
import { QualityDimension, QualityFlagType, SoilNumericField } from '../../types'

/** Field labels and units, in the order the forms show them */
export const SOIL_FIELDS: { key: SoilNumericField; label: string; unit: string; hint?: string; step?: string }[] = [
  { key: 'ph',             label: tr("Soil pH"),         unit: '',         hint: tr("Pineapple prefers 4.5 – 5.5"), step: '0.1' },
  { key: 'moisture',       label: tr("Soil moisture"),   unit: '%' },
  { key: 'nitrogen',       label: tr("Nitrogen (N)"),    unit: 'mg/kg' },
  { key: 'phosphorus',     label: tr("Phosphorus (P)"),  unit: 'mg/kg' },
  { key: 'potassium',      label: tr("Potassium (K)"),   unit: 'mg/kg' },
  { key: 'ec',             label: tr("Electrical conductivity"), unit: 'dS/m', step: '0.01' },
  { key: 'organic_matter', label: tr("Organic matter"),  unit: '%' },
]

export const WEATHER_FIELDS: { key: SoilNumericField; label: string; unit: string; hint?: string; step?: string }[] = [
  { key: 'temperature',     label: tr("Temperature"),       unit: '°C' },
  { key: 'rainfall',        label: tr("Rainfall"),          unit: tr("mm/day") },
  { key: 'humidity',        label: tr("Relative humidity"), unit: '%' },
  { key: 'solar_radiation', label: tr("Solar radiation"),   unit: 'MJ/m²' },
]

export const ALL_SOIL_FIELDS = [...SOIL_FIELDS, ...WEATHER_FIELDS]

export const fieldLabel = (key: string | null) =>
  key === 'soil_type' ? tr("Soil type") : ALL_SOIL_FIELDS.find((f) => f.key === key)?.label ?? (key ? key : tr("Whole record"))

export const soilTypeLabel = (s?: string | null) => (s === 'peat' ? tr("Peat") : s === 'mineral' ? tr("Mineral") : s ? s : '—')

export const DIMENSIONS: { key: QualityDimension; label: string; desc: string }[] = [
  { key: 'completeness', label: tr("Completeness"), desc: tr("Share of fields that have a value") },
  { key: 'validity',     label: tr("Validity"),     desc: tr("Values inside the possible range") },
  { key: 'consistency',  label: tr("Consistency"),  desc: tr("Same units, labels and plot names") },
  { key: 'uniqueness',   label: tr("Uniqueness"),   desc: tr("No repeated records") },
  { key: 'accuracy',     label: tr("Accuracy"),     desc: tr("Values that are not statistical outliers") },
  { key: 'timeliness',   label: tr("Timeliness"),   desc: tr("How recent the readings are") },
]

export const FLAG_META: Record<QualityFlagType, { label: string; cls: string }> = {
  corrected:  { label: tr("Corrected"),  cls: 'bg-blue-50 text-blue-800 ring-blue-200' },
  imputed:    { label: tr("Imputed"),    cls: 'bg-violet-50 text-violet-800 ring-violet-200' },
  outlier:    { label: tr("Outlier"),    cls: 'bg-amber-50 text-amber-800 ring-amber-200' },
  invalid:    { label: tr("Invalid"),    cls: 'bg-red-50 text-red-800 ring-red-200' },
  unreadable: { label: tr("Unreadable"), cls: 'bg-red-50 text-red-800 ring-red-200' },
  duplicate:  { label: tr("Duplicate"),  cls: 'bg-gray-100 text-gray-700 ring-gray-200' },
  unreliable: { label: tr("Unreliable"), cls: 'bg-gray-100 text-gray-700 ring-gray-200' },
}

export function FlagBadge({ type }: { type: QualityFlagType }) {
  const m = FLAG_META[type]
  return <span className={`inline-flex rounded-full px-2 py-0.5 text-[11px] font-semibold ring-1 ring-inset ${m.cls}`}>{m.label}</span>
}

export const scoreTone = (s: number) => (s >= 80 ? 'text-green-700' : s >= 60 ? 'text-amber-700' : 'text-red-700')
export const scoreBg = (s: number) => (s >= 80 ? 'bg-green-600' : s >= 60 ? 'bg-amber-500' : 'bg-red-500')

export function ScoreBadge({ score, usable = true }: { score: number; usable?: boolean }) {
  const cls = !usable ? 'bg-gray-100 text-gray-600 ring-gray-200'
    : score >= 80 ? 'bg-green-50 text-green-800 ring-green-200'
    : score >= 60 ? 'bg-amber-50 text-amber-800 ring-amber-200'
    : 'bg-red-50 text-red-800 ring-red-200'
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-semibold tabular-nums ring-1 ring-inset ${cls}`}>
      {usable ? `${Math.round(score)}/100` : tr("Not used")}
    </span>
  )
}

export const CONFIDENCE_META = {
  high:   { label: tr("High confidence"),   cls: 'bg-green-50 text-green-800 ring-green-200', dot: 'bg-green-600' },
  medium: { label: tr("Medium confidence"), cls: 'bg-amber-50 text-amber-800 ring-amber-200', dot: 'bg-amber-500' },
  low:    { label: tr("Low confidence"),    cls: 'bg-red-50 text-red-800 ring-red-200',       dot: 'bg-red-500' },
}

export function ConfidenceBadge({ level, value }: { level: 'high' | 'medium' | 'low'; value?: number }) {
  const m = CONFIDENCE_META[level]
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold ring-1 ring-inset ${m.cls}`}>
      <span className={`h-1.5 w-1.5 rounded-full ${m.dot}`} aria-hidden />
      {m.label}{value != null && <span className="tabular-nums font-medium opacity-80">· {Math.round(value)}%</span>}
    </span>
  )
}

export const todayIso = () => {
  const d = new Date()
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10)
}
