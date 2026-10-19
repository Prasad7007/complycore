import { useEffect, useState } from "react"
import { useLocation, useNavigate } from "react-router-dom"

import { AiComplianceMark } from "@/components/brand/AiComplianceMark"
import { OtpCodeInput } from "@/components/auth/OtpCodeInput"
import { Button } from "@/components/ui/button"
import { ArrowLeft, Lock } from "lucide-react"
import { AuthAlert } from "@/components/auth/AuthAlert"
import { authApi, fetchUserMeFresh } from "@/lib/api"
import { getHomePathForRoles } from "@/lib/role-routes"
import { formatOtpCountdown, getOtpCountdownSeconds } from "@/lib/auth-otp-config"
import { normalizeApiError } from "@/lib/normalize-api-error"

export default function RegisterOtpPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const emailFromState = (location.state as { email?: string } | null)?.email
  const emailFromStorage = sessionStorage.getItem("pending_register_email") || ""
  const registerEmail = emailFromState || emailFromStorage
  const [seconds, setSeconds] = useState(() => getOtpCountdownSeconds())
  const [otpValue, setOtpValue] = useState("")
  const [otpResetKey, setOtpResetKey] = useState(0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState("")

  useEffect(() => {
    if (!registerEmail) {
      navigate("/register", { replace: true })
    }
  }, [navigate, registerEmail])

  useEffect(() => {
    const t = window.setInterval(() => {
      setSeconds((s) => (s <= 0 ? 0 : s - 1))
    }, 1000)
    return () => window.clearInterval(t)
  }, [])

  const handleResend = async () => {
    if (!registerEmail) return
    setLoading(true)
    setError("")
    setOtpValue("")
    setOtpResetKey((k) => k + 1)
    try {
      await authApi.resendCode(registerEmail)
      setSeconds(getOtpCountdownSeconds())
    } catch (err: unknown) {
      const rawMessage = normalizeApiError(err, "Failed to resend code. Please try again.")
      if (/username or email not found|user not found/i.test(rawMessage)) {
        setError("Registered user with above email not found.")
      } else if (/already confirmed|already verified|cannot resend/i.test(rawMessage)) {
        setError("This account is already verified. Please login.")
      } else {
        setError(rawMessage)
      }
    } finally {
      setLoading(false)
    }
  }

  const handleVerify = async () => {
    if (otpValue.length !== 6) {
      setError("Please enter the 6-digit OTP code.")
      return
    }
    if (!registerEmail) {
      setError("Registration email not found. Please register again.")
      return
    }
    try {
      setLoading(true)
      setError("")
      const pendingPassword = sessionStorage.getItem("pending_register_password") || ""
      const res = await authApi.verifyEmail(registerEmail, otpValue, pendingPassword || undefined)

      sessionStorage.removeItem("pending_register_password")
      sessionStorage.removeItem("pending_register_email")

      // register -> email OTP -> session (no second login OTP when password + verify succeed)
      if (res?.access_token) {
        try {
          const me = await fetchUserMeFresh<{ roles?: string[]; organization?: { slug?: string } | null }>()
          navigate(getHomePathForRoles(me?.roles || [], me?.organization?.slug), { replace: true })
        } catch {
          navigate("/dashboard/default", { replace: true })
        }
        return
      }
      if (res?.mfa_required && res?.session) {
        sessionStorage.setItem("pending_login_email", registerEmail)
        sessionStorage.setItem("pending_login_session", res.session)
        navigate("/loginotp", { state: { email: registerEmail, session: res.session } })
        return
      }
      if (res?.auto_login_failed) {
        navigate("/login", {
          replace: true,
          state: {
            message:
              typeof res.detail === "string"
                ? res.detail
                : "Email verified. Please sign in with your password.",
          },
        })
        return
      }

      navigate("/login", {
        replace: true,
        state: { message: "Email verified. Please sign in with your password." },
      })
    } catch (err: unknown) {
      const rawMessage = normalizeApiError(err, "Failed to verify OTP.")
      if (/username or email not found|user not found/i.test(rawMessage)) {
        setError("Registered user with above email not found.")
      } else {
        setError(rawMessage)
      }
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="relative flex h-screen overflow-hidden">

      {/* ── Full-screen background image (small screens only) ── */}
      <div className="absolute inset-0 lg:hidden">
        <img src="/auth/register.png" alt="" className="h-full w-full object-cover" />
      </div>

      {/* ── Left: Image panel (large screens only) ── */}
      <div className="hidden w-1/2 flex-shrink-0 lg:block">
        <img
          src="/auth/register.png"
          alt="Register visual"
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
          <div className="w-full max-w-[400px] space-y-8 rounded-2xl bg-card/85 p-6 backdrop-blur-sm lg:rounded-none lg:bg-transparent lg:p-0 lg:backdrop-blur-none">
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
                <span className="font-medium text-[#1F4ED8]">{registerEmail || "your email"}</span>
              </p>
            </div>

            {error ? <AuthAlert variant="error">{error}</AuthAlert> : null}

            {/* OTP Input */}
            <div className="space-y-3">
              <OtpCodeInput key={otpResetKey} length={6} onChange={setOtpValue} onComplete={setOtpValue} />
              <p className="text-center text-xs text-muted-foreground">
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
                      Resend code
                    </button>
                  </>
                )}
              </p>
            </div>

            {/* Submit */}
            {seconds === 0 ? (
              <AuthAlert variant="info">
                This code has expired. Use <span className="font-medium text-foreground">Resend code</span> for a
                new code.
              </AuthAlert>
            ) : null}

            <Button
              type="button"
              onClick={handleVerify}
              disabled={loading || otpValue.length < 6 || seconds === 0}
              className="h-12 w-full rounded-[10px] bg-[#1F4ED8] hover:bg-[#1F4ED8]/90"
            >
              {loading ? "Verifying..." : "Register"} <Lock className="ml-2 h-4 w-4" />
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}