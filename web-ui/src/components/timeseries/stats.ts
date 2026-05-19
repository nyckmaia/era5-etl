/** Basic descriptive statistics for a plotted series (nulls ignored). */
export interface SeriesStats {
  count: number;
  min: number | null;
  max: number | null;
  mean: number | null;
  std: number | null; // sample standard deviation (n-1)
  variance: number | null; // sample variance (n-1)
  iqr: number | null; // Q3 - Q1
}

function percentile(sorted: number[], p: number): number {
  if (sorted.length === 1) return sorted[0];
  const idx = p * (sorted.length - 1);
  const lo = Math.floor(idx);
  const hi = Math.ceil(idx);
  if (lo === hi) return sorted[lo];
  return sorted[lo] + (sorted[hi] - sorted[lo]) * (idx - lo);
}

export function computeStats(y: (number | null)[]): SeriesStats {
  const v = y.filter((n): n is number => n != null && Number.isFinite(n));
  const n = v.length;
  if (n === 0) {
    return {
      count: 0,
      min: null,
      max: null,
      mean: null,
      std: null,
      variance: null,
      iqr: null,
    };
  }
  const mean = v.reduce((a, b) => a + b, 0) / n;
  const variance =
    n > 1 ? v.reduce((a, b) => a + (b - mean) ** 2, 0) / (n - 1) : 0;
  const sorted = [...v].sort((a, b) => a - b);
  return {
    count: n,
    min: sorted[0],
    max: sorted[n - 1],
    mean,
    std: Math.sqrt(variance),
    variance,
    iqr: percentile(sorted, 0.75) - percentile(sorted, 0.25),
  };
}

export function fmtStat(n: number | null): string {
  if (n == null) return "—";
  if (Math.abs(n) >= 1000 || (n !== 0 && Math.abs(n) < 0.001)) {
    return n.toExponential(3);
  }
  return n.toFixed(3);
}
