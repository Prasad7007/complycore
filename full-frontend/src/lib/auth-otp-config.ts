/**
 * OTP countdown shown on login/register OTP screens.
 * Must match backend `OTP_EXPIRE_MINUTES` (see `apis/core/mail.py`, env `OTP_EXPIRE_MINUTES`).
 * Set `VITE_OTP_EXPIRE_MINUTES` in the frontend env if you change the server default.
 */
export function getOtpCountdownSeconds(): number {
  const raw = import.meta.env.VITE_OTP_EXPIRE_MINUTES
  const minutes =
    raw !== undefined && raw !== "" ? Number(String(raw).trim()) : NaN
  if (Number.isFinite(minutes) && minutes > 0) {
    return Math.round(minutes * 60)
  }
  return 60
}

/** Display mm:ss for the OTP countdown. */
export function formatOtpCountdown(totalSeconds: number): string {
  const s = Math.max(0, Math.floor(totalSeconds))
  const m = Math.floor(s / 60)
  const sec = s % 60
  return `${m}:${String(sec).padStart(2, "0")}`
}
