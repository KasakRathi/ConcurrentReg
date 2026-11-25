import type { Category } from "./types";

// Chart and badge colours. They mirror the CSS tokens in styles/index.css (charts need raw values).
export const COLORS = {
  mint: "#6ee7b7",
  amber: "#fbbf24",
  rose: "#fb7185",
  violet: "#a78bfa",
  sky: "#7dd3fc",
  grid: "#1b2024",
  axis: "#5b646b",
  text: "#aab2b8",
} as const;

export const CATEGORY_STYLE: Record<Category, { color: string; label: string; meaning: string }> = {
  SUCCESS: { color: COLORS.mint, label: "Registered", meaning: "HTTP 201: the transaction committed one registration." },
  DUPLICATE: { color: COLORS.violet, label: "Duplicate", meaning: "HTTP 409: the student already held this section." },
  COURSE_FULL: { color: COLORS.amber, label: "Course full", meaning: "HTTP 409: no seats were left when the row lock was granted." },
  QUEUE_FULL: { color: COLORS.rose, label: "Queue full", meaning: "HTTP 503 (provisional): the bounded queue refused the request." },
  ADMISSION_REJECTED: { color: "#e879f9", label: "Admission refused", meaning: "HTTP 503 (distinct message): IASL admission control refused the request before it reached the queue." },
  CLIENT_ERROR: { color: "#f97316", label: "Client error", meaning: "A 4xx answer that is not part of the registration contract." },
  SERVER_ERROR: { color: "#ef4444", label: "Server error", meaning: "A 5xx answer other than the queue-full and admission refusals." },
  TIMEOUT: { color: "#fb923c", label: "Timeout", meaning: "No response within the client timeout." },
  CONNECTION_ERROR: { color: "#f43f5e", label: "Connection error", meaning: "The client could not reach the server." },
  UNKNOWN: { color: "#94a3b8", label: "Unclassified", meaning: "An answer the generator does not recognise (never counted as success)." },
  NOT_DISPATCHED: { color: "#475569", label: "Not dispatched", meaning: "The run stopped before this request was sent." },
};
