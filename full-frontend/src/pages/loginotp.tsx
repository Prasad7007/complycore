import { useEffect, useState } from "react"
import { useNavigate, useLocation } from "react-router-dom"

import { AiComplianceMark } from "@/components/brand/AiComplianceMark"
import { OtpCodeInput } from "@/components/auth/OtpCodeInput"
import { Button } from "@/components/ui/button"
import { ArrowLeft, KeyRound } from "lucide-react"
import { AuthAlert } from "@/components/auth/AuthAlert"
import { authApi, fetchUserMeFresh } from "@/lib/api"
import { getHomePathForRoles } from "@/lib/role-routes"
import { formatOtpCountdown, getOtpCountdownSeconds } from "@/lib/auth-otp-config"
import { normalizeApiError } from "@/lib/normalize-api-error"

export default function LoginOtpPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const state = (location.state as { email?: string; session?: string } | null) || {}
  const email = state.email || sessionStorage.getItem("pending_login_email") || ""
  const session = state.session || sessionStorage.getItem("pending_login_session") || ""
  
  const [seconds, setSeconds] = useState(() => getOtpCountdownSeconds())
  const [otpValue, setOtpValue] = useState("")
  const [otpResetKey, setOtpResetKey] = useState(0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState("")

  useEffect(() => {
    if (!email || !session) return
    const t = window.setInterval(() => {
      setSeconds((s) => (s <= 0 ? 0 : s - 1))
    }, 1000)
    return () => window.clearInterval(t)
  }, [email, session])

  useEffect(() => {
    if (!email || !session) {
      navigate("/login", { replace: true })
    }
  }, [email, session, navigate])

  const handleVerify = async () => {
    if (otpValue.length !== 6) {
      setError("Please enter the 6-digit OTP code.")
      return
    }
    setLoading(true)
    setError("")
    try {
      await authApi.verifyOtp(email, otpValue, session)
      sessionStorage.removeItem("pending_login_email")
      sessionStorage.removeItem("pending_login_session")
      try {
        const me = await fetchUserMeFresh<{ roles?: string[]; organization?: { slug?: string } | null }>()
        navigate(getHomePathForRoles(me?.roles || [], me?.organization?.slug), { replace: true })
      } catch {
        navigate("/dashboard/default", { replace: true })
      }
    } catch (err: unknown) {
      setError(normalizeApiError(err, "Failed to verify OTP. Please try again."))
    } finally {
      setLoading(false)
    }
  }

  const handleResend = async () => {
    if (!email || !session) return
    setLoading(true)
    setError("")
    setOtpValue("")
    setOtpResetKey((k) => k + 1)
    try {
      await authApi.resendOtp(email, session)
      setSeconds(getOtpCountdownSeconds())
    } catch (err: unknown) {
      setError(normalizeApiError(err, "Failed to resend OTP. Please try again."))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="relative flex h-screen overflow-hidden">

      {/* ── Full-screen background image (small screens only) ── */}
      <div className="absolute inset-0 lg:hidden">
        <img src="/auth/login.png" alt="" className="h-full w-full object-cover" />
      </div>

      {/* ── Left: Image panel (large screens only) ── */}
      <div className="hidden w-1/2 flex-shrink-0 lg:block">
        <img
          src="/auth/login.png"
          alt="Login visual"
          className="h-full w-full object-cover"
        />
      </div>

      {/* ── Right: Form ── */}
      <div className="relative flex w-full flex-col overflow-y-auto bg-transparent lg:w-1/2 lg:bg-background">
        {/* Logo */}
        <div className="flex-shrink-0 px-10 pt-8">
          <AiComplianceMark className="h-14 w-auto" />
        </div>

        {/* Centered Content */}
        <div className="flex flex-1 items-start justify-center px-4 py-6 lg:items-center lg:px-16">
          <div className="w-full max-w-[400px] space-y-8 rounded-2xl bg-card/90 p-6 backdrop-blur-sm lg:rounded-none lg:bg-transparent lg:p-0 lg:backdrop-blur-none">
            {/* Header */}
            <div className="space-y-2">
              <div className="flex items-center gap-3">
                <button
                  type="button"
                  onClick={() => navigate(-1)}
                  className="text-muted-foreground hover:text-foreground"
                  aria-label="Back"
                >
                  <ArrowLeft className="h-5 w-5" />
                </button>
                <h3 className="text-xl font-bold text-foreground">Verify OTP Code</h3>
              </div>
              <p className="text-sm leading-5 text-muted-foreground">
                Please check your email. An OTP has been sent to{" "}
                <span className="font-medium text-[#1F4ED8]">{email || "your email"}</span>
              </p>
            </div>

            {error ? (
              <AuthAlert variant="error">{error}</AuthAlert>
            ) : null}

            {/* OTP Input */}
            <div className="space-y-3">
              <OtpCodeInput key={otpResetKey} length={6} onChange={setOtpValue} onComplete={setOtpValue} />
              <p className="flex items-center justify-center gap-2 text-center text-xs text-muted-foreground">
                {seconds > 0 ? (
                  <>
                    Code expires in{" "}
                    <span className="font-medium text-foreground">
                      {formatOtpCountdown(seconds)}
                    </span>
                  </>
                ) : (
                  <>
                    Didn&apos;t receive?{" "}
                    <button
                      type="button"
                      className="font-medium text-[#1F4ED8] hover:underline disabled:opacity-60"
                      onClick={handleResend}
                      disabled={loading}
                    >
                      Resend OTP
                    </button>
                  </>
                )}
              </p>
            </div>

            {/* Submit */}
            {seconds === 0 ? (
              <AuthAlert variant="info">
                This code has expired. Use <span className="font-medium text-foreground">Resend OTP</span> for a
                new code.
              </AuthAlert>
            ) : null}

            <Button
              type="button"
              onClick={handleVerify}
              disabled={loading || otpValue.length < 6 || seconds === 0}
              className="h-12 w-full rounded-[10px] bg-[#1F4ED8] hover:bg-[#1F4ED8]/90"
            >
              {loading ? "Verifying..." : "Login"} <KeyRound className="ml-2 h-4 w-4" />
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}