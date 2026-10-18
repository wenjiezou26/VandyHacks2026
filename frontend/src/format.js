export function formatMoney(value) {
  return Number(value).toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

// A value from a benefit's "numbers used" table: all of them are dollars.
export function formatNumberUsed(value) {
  return typeof value === "number" ? `$${formatMoney(value)}` : String(value);
}
