import { useState, useEffect } from "react"
import { useNavigate, useLocation } from "react-router-dom"

import { AiComplianceMark } from "@/components/brand/AiComplianceMark"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Eye, EyeClosed, UserRound } from "lucide-react"
import { AuthAlert } from "@/components/auth/AuthAlert"
import { authApi, usersApi } from "@/lib/api"
import { normalizeApiError } from "@/lib/normalize-api-error"
import { getHomePathForRoles } from "@/lib/role-routes"

export default function LoginPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const [showPassword, setShowPassword] = useState(false)
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [loading, setLoading] = useState(false)
  const [checkingSession, setCheckingSession] = useState(true)
  const [error, setError] = useState("")
  const [needsVerification, setNeedsVerification] = useState(false)
  const [infoMessage, setInfoMessage] = useState("")

  // Check for an active session on mount
  useEffect(() => {
    let active = true
    const checkActiveSession = async () => {
      try {
        const me = await usersApi.getMe()
        if (!active) return
        if (me && me.roles) {
          const home = getHomePathForRoles(me.roles, me.organization?.slug)
          navigate(home, { replace: true })
        } else {
          setCheckingSession(false)
        }
      } catch {
        if (active) setCheckingSession(false)
      }
    }
    checkActiveSession()
    return () => {
      active = false
    }
  }, [navigate])

  useEffect(() => {
    const msg = (location.state as { message?: string } | null)?.message
    if (msg) setInfoMessage(msg)
  }, [location.state])

  // Hide the form with a loading state while checking the session
  if (checkingSession) {
    return (
      <div className="flex h-screen items-center justify-center bg-background text-sm text-muted-foreground">
        Loading…
      </div>
    )
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

      {/* ── Right: Form side ── */}
      <div className="relative flex w-full flex-col overflow-y-auto bg-transparent lg:w-1/2 lg:bg-background">

        {/* Logo — pinned top-left */}
        <div className="flex-shrink-0 px-12 pt-10">
          <AiComplianceMark className="h-14 w-auto" />
        </div>

        {/* Form — starts close below logo, no excessive centering */}
        <div className="flex flex-1 items-start justify-center px-4 pt-6 pb-6 lg:px-12 lg:pt-12 lg:pb-10">
          <div className="w-full max-w-[360px] rounded-2xl bg-card/90 p-6 backdrop-blur-sm lg:rounded-none lg:bg-transparent lg:p-0 lg:backdrop-blur-none">

            {/* Heading */}
            <div className="mb-8">
              <h2 className="text-[22px] font-bold leading-tight text-foreground">Login Account</h2>
              <p className="mt-1.5 text-sm text-muted-foreground">
                Please enter the username and password sent to you via email.
              </p>
            </div>

            {infoMessage ? (
              <AuthAlert variant="info" className="mb-4">
                {infoMessage}
              </AuthAlert>
            ) : null}

            <form
              className="flex flex-col gap-5"
              onSubmit={async (e) => {
                e.preventDefault()
                setError("")
                setNeedsVerification(false)
                setLoading(true)
                try {
                  const response = await authApi.login(email, password)
                  if (response.mfa_required && response.session) {
                    // Navigate to OTP page with session info
                    const normalizedEmail = email.trim().toLowerCase()
                    sessionStorage.setItem("pending_login_email", normalizedEmail)
                    sessionStorage.setItem("pending_login_session", response.session)
                    navigate("/loginotp", { state: { email: normalizedEmail, session: response.session } })
                  } else {
                    setError("MFA is required but the login challenge session was not returned.")
                  }
                } catch (err: unknown) {
                  const rawMessage = normalizeApiError(err, "Login failed. Please check your credentials.")
                  const isUnknownUser = /username or email not found|user not found/i.test(rawMessage)
                  const msg = isUnknownUser
                    ? "Registered user with above email not found."
                    : rawMessage
                  if (msg.toLowerCase().includes("not verified") || msg.toLowerCase().includes("not confirmed")) {
                    setNeedsVerification(true)
                    sessionStorage.setItem("pending_register_email", email.trim().toLowerCase())
                  }
                  setError(msg)
                } finally {
                  setLoading(false)
                }
              }}
            >
              {/* Email */}
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="email" className="text-sm font-medium text-foreground">
                  Email address
                </Label>
                <Input
                  id="email"
                  placeholder="Your registered email"
                  type="email"
                  autoComplete="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  required
                  className="h-11 rounded-lg border-border bg-background px-3 text-sm placeholder:text-muted-foreground/60"
                />
              </div>

              {/* Password */}
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="password" className="text-sm font-medium text-foreground">
                  Password
                </Label>
                <div className="relative">
                  <Input
                    id="password"
                    type={showPassword ? "text" : "password"}
                    placeholder="Password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    required
                    className="h-11 rounded-lg border-border bg-background px-3 pr-10 text-sm placeholder:text-muted-foreground/60"
                    autoComplete="current-password"
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword((v) => !v)}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                    aria-label={showPassword ? "Hide password" : "Show password"}
                  >
                    {showPassword ? <Eye size={17} /> : <EyeClosed size={17} />}
                  </button>
                </div>
                <div className="text-right">
                  <button
                    type="button"
                    onClick={() => navigate("/forgot-password")}
                    className="text-xs font-medium text-[#1F4ED8] hover:underline"
                  >
                    Forgot password?
                  </button>
                </div>
              </div>

              {/* Buttons */}
              <div className="mt-2 flex flex-col gap-3">
                {error ? (
                  <AuthAlert variant="error" className="mb-1">
                    {error}
                    {needsVerification && (
                      <button
                        type="button"
                        className="mt-2 block w-full rounded-lg bg-[#1F4ED8] py-2 text-xs font-semibold text-white hover:bg-[#1F4ED8]/90"
                        onClick={() =>
                          navigate("/registerotp", { state: { email: email.trim().toLowerCase() } })
                        }
                      >
                        Verify Email →
                      </button>
                    )}
                  </AuthAlert>
                ) : null}
                <Button
                  type="submit"
                  disabled={loading}
                  className="h-12 w-full rounded-[10px] bg-[#1F4ED8] text-sm font-semibold hover:bg-[#1F4ED8]/90"
                >
                  {loading ? "Please wait..." : "Continue →"}
                </Button>

                <div className="flex justify-center">
                  <Button
                    variant="outline"
                    className="h-9 rounded-[10px] border px-5 text-xs font-normal"
                    type="button"
                    disabled={true}
                    onClick={() => navigate("/register")}
                  >
                    <UserRound className="mr-1.5 h-3.5 w-3.5 text-muted-foreground" />
                    Don&apos;t have an account?&nbsp;
                    <span className="font-semibold text-[#1F4ED8] opacity-50">Register</span>
                  </Button>
                </div>
              </div>
            </form>

          </div>
        </div>
      </div>
    </div>
  )
}