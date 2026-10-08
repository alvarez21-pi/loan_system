import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/**
 * Today's date as YYYY-MM-DD in the BROWSER'S LOCAL time, not UTC.
 * `new Date().toISOString()` reports UTC — for a browser set to Africa/
 * Dar_es_Salaam (UTC+3), that shows YESTERDAY's date for the first three
 * hours after local midnight. Every date field in the app that defaults
 * to "today" must use this instead.
 */
export function localDateString(date: Date = new Date()): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}
