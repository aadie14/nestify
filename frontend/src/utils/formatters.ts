export function formatCurrency(value: number | null | undefined): string {
  if (value == null || Number.isNaN(Number(value))) return '...';
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 2 }).format(
    Number(value),
  );
}

export function formatCurrencyINR(value: number | null | undefined): string {
  if (value == null || Number.isNaN(Number(value))) return '...';
  return new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 2 }).format(
    Number(value),
  );
}

export function formatPercent(value: number | null | undefined, digits = 1): string {
  if (value == null || Number.isNaN(Number(value))) return '...';
  return `${(Number(value) * 100).toFixed(digits)}%`;
}

export function formatNumber(value: number | null | undefined): string {
  if (value == null || Number.isNaN(Number(value))) return '0';
  return new Intl.NumberFormat('en-US').format(Number(value));
}

export function toTitleCase(value: string): string {
  return value
    .split(/[_\s-]+/)
    .filter(Boolean)
    .map((part) => `${part[0].toUpperCase()}${part.slice(1).toLowerCase()}`)
    .join(' ');
}
