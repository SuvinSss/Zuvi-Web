import { describe, expect, it } from 'vitest'
import { checkSheet, MAX_SHEET_BYTES } from './ImportPage'

describe('checkSheet', () => {
  it('accepts xlsx and csv', () => {
    expect(checkSheet(new File(['a'], 'p.xlsx'))).toBeNull()
    expect(checkSheet(new File(['a'], 'P.CSV'))).toBeNull()
  })
  it('rejects other types', () => expect(checkSheet(new File(['a'], 'p.xls'))).toMatch(/\.xlsx or \.csv/))
  it('rejects oversize files', () => {
    const big = new File(['a'], 'p.xlsx')
    Object.defineProperty(big, 'size', { value: MAX_SHEET_BYTES + 1 })
    expect(checkSheet(big)).toMatch(/limit/)
  })
})
