// Helpers for the 24-bit hours_mask used by the coverage index.

export function maskToHours(mask: number): number[] {
  const out: number[] = [];
  for (let h = 0; h < 24; h++) {
    if ((mask >>> h) & 1) out.push(h);
  }
  return out;
}

export function hoursToMask(hours: number[]): number {
  return hours.reduce((m, h) => (h >= 0 && h < 24 ? m | (1 << h) : m), 0);
}

export function popcount(mask: number): number {
  let m = mask;
  let n = 0;
  while (m) {
    m &= m - 1;
    n += 1;
  }
  return n;
}
