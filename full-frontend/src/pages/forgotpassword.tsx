import { useState } from "react"
import { useNavigate } from "react-router-dom"

import { AuthSplitLayout } from "@/components/auth/layout"
import { OtpCodeInput } from "@/components/auth/OtpCodeInput"
import { AiComplianceMark } from "@/components/brand/AiComplianceMark"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Eye, EyeClosed, UserRound } from "lucide-react"
import { AuthAlert } from "@/components/auth/AuthAlert"
import { PasswordUpdateSuccessModal } from "@/components/models/PasswordUpdateSuccessModal"
import { authApi } from "@/lib/api"
import { normalizeApiError } from "@/lib/normalize-api-error"

type Step = "forgot" | "verify" | "newpass"

// Shared bottom CTA used on all steps
function BottomRegisterCta({ onClick }: { onClick: () => void }) {
  return (
    <Button
      variant="outline"
      className="h-9 rounded-[6px] border border-border px-5 text-xs font-normal"
      type="button"
      disabled={true}
      onClick={onClick}
    >
      <UserRound className="mr-1.5 h-3.5 w-3.5 text-muted-foreground" />
      Don&apos;t have an account?&nbsp;
      <span className="font-semibold text-[#1F4ED8] opacity-50">Register</span>
    </Button>
  )
}

// ── Step 1: Forgot Password ────────────────────────────────────────
function ForgotStep({
  email,
  setEmail,
  loading,
  error,
  onForgot,
  onBack,
}: {
  email: string
  setEmail: (v: string) => void
  loading: boolean
  error: string
  onForgot: () => Promise<void>
  onBack: () => void
}) {
  const navigate = useNavigate()

  return (
    <AuthSplitLayout
      brand={<AiComplianceMark className="h-14 w-auto mb-10" />}
      title="Forgot Password"
      imageSrc="/auth/temproarypassword.png"
      bottomCta={<BottomRegisterCta onClick={() => navigate("/register")} />}
    >
      <form
        className="flex flex-col gap-8 justify-center"
        onSubmit={(e) => {
          e.preventDefault()
          onForgot()
        }}
      >
        {error ? <AuthAlert variant="error">{error}</AuthAlert> : null}
        {/* Email */}
        <div className="flex flex-col ">
          <Label htmlFor="fp-email" className="text-sm font-medium text-foreground">
            Email Address
          </Label>
          <Input
            id="fp-email"
            type="email"
            placeholder="Your registered email"
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="h-11 rounded-lg border-border bg-background px-3 mb-10 text-sm placeholder:text-muted-foreground/60"
          />
        </div>

        {/* Buttons */}
        <div className="flex flex-col gap-10">
          <Button
            type="submit"
            className="h-12 w-full rounded-[10px] bg-[#1F4ED8] text-sm font-semibold hover:bg-[#1F4ED8]/90"
            disabled={loading}
          >
            {loading ? "Sending..." : "Reset Password →"}
          </Button>

          <div className="flex justify-center gap-10">
            <button
              type="button"
              onClick={onBack}
              className="text-sm font-medium text-[#1F4ED8] hover:underline"
            >
              Back to Login
            </button>
          </div>
        </div>
      </form>
    </AuthSplitLayout>
  )
}

// ── Step 2: Verification ──────────────────────────────────────────
function VerifyStep({
  email,
  otp,
  setOtp,
  otpResetKey,
  loading,
  error,
  onVerify,
  onResend,
}: {
  email: string
  otp: string
  setOtp: (v: string) => void
  otpResetKey: number
  loading: boolean
  error: string
  onVerify: () => void
  onResend: () => Promise<void>
}) {
  const navigate = useNavigate()

  return (
    <AuthSplitLayout
      brand={<AiComplianceMark className="h-14 w-auto" />}
      imageSrc="/auth/temproarypassword.png"
      bottomCta={<BottomRegisterCta onClick={() => navigate("/register")} />}
    >
      <form
        className="flex flex-col gap-6"
        onSubmit={(e) => {
          e.preventDefault()
          onVerify()
        }}
      >
        <h2 className="text-[22px] font-bold leading-tight text-foreground">
          Verification
        </h2>
        {error ? <AuthAlert variant="error">{error}</AuthAlert> : null}
        {/* OTP section */}
        <div className="flex flex-col items-center gap-4">
          <p className="text-sm font-semibold text-foreground">Enter Verification Code</p>
          <OtpCodeInput key={otpResetKey} length={6} onChange={setOtp} onComplete={setOtp} />
          <p className="text-xs text-muted-foreground">
            Didn&apos;t receive a code?{" "}
            <button
              type="button"
              className="font-medium text-[#1F4ED8] hover:underline disabled:opacity-60"
              onClick={onResend}
              disabled={loading || !email}
            >
              Resend
            </button>
          </p>
        </div>

        <Button
          type="submit"
          className="h-12 w-full rounded-[10px] bg-[#1F4ED8] text-sm font-semibold hover:bg-[#1F4ED8]/90"
          disabled={loading || otp.length !== 6}
        >
          {loading ? "Verifying..." : "Send"}
        </Button>
      </form>
    </AuthSplitLayout>
  )
}

// ── Step 3: New Password ──────────────────────────────────────────
function NewPasswordStep({
  email,
  code,
}: {
  email: string
  code: string
}) {
  const navigate = useNavigate()
  const [showNew, setShowNew] = useState(false)
  const [showConfirm, setShowConfirm] = useState(false)
  const [newPassword, setNewPassword] = useState("")
  const [confirmPassword, setConfirmPassword] = useState("")
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState("")
  const [successOpen, setSuccessOpen] = useState(false)

  return (
    <AuthSplitLayout
      brand={<AiComplianceMark className="h-14 w-auto" />}
      title="New Password"
      imageSrc="/auth/temproarypassword.png"
      bottomCta={<BottomRegisterCta onClick={() => navigate("/register")} />}
    >
      <form
        className="flex flex-col  gap-10"
        onSubmit={async (e) => {
          e.preventDefault()
          setError("")

          if (!email.trim() || !code.trim() || code.trim().length !== 6) {
            setError("Invalid reset code. Please go back and try again.")
            return
          }
          if (newPassword.length < 8) {
            setError("New password must be at least 8 characters.")
            return
          }
          if (newPassword !== confirmPassword) {
            setError("Passwords do not match.")
            return
          }

          try {
            setLoading(true)
            await authApi.confirmForgotPassword(email.trim(), code.trim(), newPassword)
            setSuccessOpen(true)
          } catch (err) {
            const message = err instanceof Error ? err.message : "Failed to reset password. Please try again."
            setError(message)
          } finally {
            setLoading(false)
          }
        }}
      >
        {/* New Password */}
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="np-new" className="text-sm font-medium text-foreground">
            Enter New Password
          </Label>
          <div className="relative">
            <Input
              id="np-new"
              type={showNew ? "text" : "password"}
              placeholder="At least 8 characters"
              className="h-11 rounded-lg border-border bg-background px-3 pr-10 text-sm placeholder:text-muted-foreground/60"
              autoComplete="new-password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
            />
            <button
              type="button"
              onClick={() => setShowNew((v) => !v)}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
              aria-label={showNew ? "Hide" : "Show"}
            >
              {showNew ? <Eye size={17} /> : <EyeClosed size={17} />}
            </button>
          </div>
        </div>

        {/* Confirm Password */}
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="np-confirm" className="text-sm font-medium text-foreground">
            Confirm Password
          </Label>
          <div className="relative">
            <Input
              id="np-confirm"
              type={showConfirm ? "text" : "password"}
              placeholder="Re-enter password"
              className="h-11 rounded-lg border-border bg-background px-3 pr-10 text-sm placeholder:text-muted-foreground/60"
              autoComplete="new-password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
            />
            <button
              type="button"
              onClick={() => setShowConfirm((v) => !v)}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
              aria-label={showConfirm ? "Hide" : "Show"}
            >
              {showConfirm ? <Eye size={17} /> : <EyeClosed size={17} />}
            </button>
          </div>
        </div>

        {error ? <AuthAlert variant="error">{error}</AuthAlert> : null}

        <Button
          type="submit"
          className="mt-2 h-12 w-full rounded-[10px] bg-[#1F4ED8] text-sm font-semibold hover:bg-[#1F4ED8]/90"
          disabled={loading}
        >
          {loading ? "Updating..." : "Reset Password"}
        </Button>
      </form>

      <PasswordUpdateSuccessModal
        open={successOpen}
        onClose={() => {
          setSuccessOpen(false)
          navigate("/login")
        }}
      />
    </AuthSplitLayout>
  )
}

// ── Main Page ─────────────────────────────────────────────────────
export default function ForgotPasswordPage() {
  const navigate = useNavigate()
  const [step, setStep] = useState<Step>("forgot")
  const [email, setEmail] = useState("")
  const [otp, setOtp] = useState("")
  const [otpResetKey, setOtpResetKey] = useState(0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState("")

  if (step === "verify")
    return (
      <VerifyStep
        email={email}
        otp={otp}
        setOtp={setOtp}
        otpResetKey={otpResetKey}
        loading={loading}
        error={error}
        onVerify={() => {
          setError("")
          setStep("newpass")
        }}
        onResend={async () => {
          setLoading(true)
          setError("")
          setOtp("")
          setOtpResetKey((k) => k + 1)
          try {
            await authApi.forgotPassword(email.trim())
          } catch (err: unknown) {
            setError(normalizeApiError(err, "Failed to resend code. Please try again."))
          } finally {
            setLoading(false)
          }
        }}
      />
    )

  if (step === "newpass") return <NewPasswordStep email={email} code={otp} />

  return (
    <ForgotStep
      email={email}
      setEmail={setEmail}
      loading={loading}
      error={error}
      onForgot={async () => {
        setLoading(true)
        setError("")
        try {
          await authApi.forgotPassword(email.trim())
          setError("")
          setStep("verify")
        } catch (err: unknown) {
          const rawMessage = normalizeApiError(err, "Failed to send reset code. Please try again.")
          if (/username or email not found|user not found/i.test(rawMessage)) {
            setError("Registered user with above email not found.")
          } else {
            setError(rawMessage)
          }
        } finally {
          setLoading(false)
        }
      }}
      onBack={() => navigate("/login")}
    />
  )
}