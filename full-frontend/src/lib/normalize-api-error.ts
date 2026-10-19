/**
 * Turn FastAPI / fetch error payloads into a single user-facing string.
 */

export function formatFastApiDetail(detail: unknown): string {
  if (detail == null || detail === "") return ""
  if (typeof detail === "string") return detail
  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        if (item != null && typeof item === "object" && "msg" in item) {
          return String((item as { msg?: string }).msg ?? "").trim()
        }
        return typeof item === "string" ? item : JSON.stringify(item)
      })
      .filter(Boolean)
      .join("; ")
  }
  if (typeof detail === "object" && detail !== null && "message" in detail) {
    return String((detail as { message?: string }).message ?? "").trim()
  }
  try {
    return JSON.stringify(detail)
  } catch {
    return String(detail)
  }
}

export function normalizeApiError(
  err: unknown,
  fallback = "Something went wrong. Please try again.",
): string {
  if (err instanceof Error) {
    const m = err.message?.trim()
    return m || fallback
  }
  if (typeof err === "string" && err.trim()) return err.trim()
  return fallback
}
