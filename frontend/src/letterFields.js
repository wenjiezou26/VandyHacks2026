import { formatMoney } from "./format";
import { documentText, t } from "./strings";

const MONEY_FIELDS = new Set(["gross_monthly_benefit", "part_b_deduction", "net_payment", "ending_balance", "monthly_rent", "gross_pay"]);

// One entry of a list read from a letter: a payment ({description,
// amount}), a person ({name}), or plain text.
function formatListItem(item) {
  if (item === null || typeof item !== "object") return String(item);
  if (typeof item.amount === "number") {
    const money = `$${formatMoney(item.amount)}`;
    return item.description ? `${item.description}: ${money}` : money;
  }
  if (item.name) return item.name;
  return Object.values(item).filter((v) => v !== null && v !== "").join(" ");
}

// How a fact read from a letter is shown (null = nothing to show).
export function formatField(key, value, language) {
  if (value === null || value === undefined || value === "") return null;
  if (typeof value === "boolean") return t(language, value ? "yes" : "no");
  if (MONEY_FIELDS.has(key) && typeof value === "number") return `$${formatMoney(value)}`;
  if (Array.isArray(value)) {
    if (value.length === 0) return null;
    if (key === "required_documents") return value.map((item) => documentText(language, String(item))).join("; ");
    return value.map((item) => formatListItem(item)).join("; ");
  }
  return String(value);
}
