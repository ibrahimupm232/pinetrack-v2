import { ms1 } from './ms1'
import { ms2 } from './ms2'
import { ms3 } from './ms3'
import { ms4 } from './ms4'
import { ms5 } from './ms5'

/** Bahasa Melayu translations, keyed by the English text used in the UI */
export const ms: Record<string, string> = { ...ms5, ...ms1, ...ms2, ...ms3, ...ms4 }
