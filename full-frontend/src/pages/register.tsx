import { useState } from "react"
import { useNavigate } from "react-router-dom"

import { AiComplianceMark } from "@/components/brand/AiComplianceMark"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Eye, EyeClosed, KeyRound } from "lucide-react"
import { AuthAlert } from "@/components/auth/AuthAlert"
import { PasswordValidation } from "@/components/auth/PasswordValidation"
import { authApi } from "@/lib/api"
import { normalizeApiError } from "@/lib/normalize-api-error"

export default function RegisterPage() {
  const navigate = useNavigate()
  const [showPassword, setShowPassword] = useState(false)
  const [showConfirm, setShowConfirm] = useState(false)
  const [fullName, setFullName] = useState("")
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [confirmPassword, setConfirmPassword] = useState("")
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState("")
  const [hasTriedSubmit, setHasTriedSubmit] = useState(false)
const [emailTimeout, setEmailTimeout] = useState<ReturnType<typeof setTimeout> | null>(null)

  const hasMinLength = password.length >= 8
  const hasMixedCase = /[A-Z]/.test(password) && /[a-z]/.test(password)
  const hasSpecialCharacter = /[!@#$%^&*()_+\-=\[\]{};':"\\|,.<>\/?]/.test(password)
  const isPasswordCompliant = hasMinLength && hasMixedCase && hasSpecialCharacter
  const showPasswordChecks = password.length > 0 && !isPasswordCompliant

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

        {/* Centered Form */}
        <div className="flex flex-1 items-start justify-center px-4 py-6 lg:items-center lg:px-16">
          <div className="w-full max-w-[400px] rounded-2xl bg-card/85 p-6 backdrop-blur-sm lg:rounded-none lg:bg-transparent lg:p-0 lg:backdrop-blur-none">
            {/* Heading */}
            <div className="mb-5">
              <h2 className="text-2xl font-bold text-foreground">Register Now</h2>
              <p className="mt-1 text-sm text-muted-foreground">Get started with ComplyCore</p>
            </div>

            <form
              className="grid gap-3"
              onSubmit={async (e) => {
                e.preventDefault()
                setError("")
                setHasTriedSubmit(true)
                if (!hasMinLength || !hasMixedCase || !hasSpecialCharacter) {
                  setError("Password does not meet the required criteria.")
                  return
                }
                if (password !== confirmPassword) {
                  setError("Passwords do not match.")
                  return
                }
                try {
                  setLoading(true)
                  await authApi.signup({
                    email: email.trim().toLowerCase(),
                    password,
                    full_name: fullName.trim(),
                  })
                  sessionStorage.setItem("pending_register_email", email.trim().toLowerCase())
                  sessionStorage.setItem("pending_register_password", password)
                  navigate("/registerotp", {
                    state: { email: email.trim().toLowerCase() },
                  })
                } catch (err: unknown) {
                  setError(normalizeApiError(err, "Failed to register. Please try again."))
                } finally {
                  setLoading(false)
                }
              }}
            >
              {/* Full Name */}
              <div className="grid gap-1.5">
                <Label htmlFor="name" className="text-sm font-medium">Full name</Label>
                <Input
                  id="name"
                  placeholder="Your name"
                  autoComplete="name"
                  className="h-10 bg-background"
                  value={fullName}
                  onChange={(e) => setFullName(e.target.value)}
                  required
                />
              </div>

              {/* Email */}
              <div className="grid gap-1.5">
                <Label htmlFor="email" className="text-sm font-medium">Email address</Label>
                <Input
                  id="email"
                  placeholder="Your official email"
                  type="email"
                  autoComplete="email"
                  className="h-10 bg-background"
                  value={email}
                  onChange={(e) => {
                    const value = e.target.value
                    setEmail(value)
                  
                    if (error) setError("")
                  
                    // clear previous timeout
                    if (emailTimeout) clearTimeout(emailTimeout)
                  
                    // set new timeout (debounce)
                    const timeout = setTimeout(async () => {
                      if (!value) return
                  
                      try {
                        await authApi.checkEmail(value)
                        setError("")
                      } catch (err) {
                        setError(normalizeApiError(err))
                      }
                    }, 500)
                  
                    setEmailTimeout(timeout)
                  }}
                  required
                />
              </div>

              {/* Password */}
              <div className="grid gap-1.5">
                <Label htmlFor="password" className="text-sm font-medium">Password</Label>
                <div className="relative">
                  <Input
                    id="password"
                    type={showPassword ? "text" : "password"}
                    placeholder="Your Password"
                    className="h-10 bg-background pr-10"
                    autoComplete="new-password"
                    value={password}
                    onChange={(e) => {
                      const value = e.target.value
                      setPassword(value)
                    
                      const hasMin = value.length >= 8
                      const hasCase = /[A-Z]/.test(value) && /[a-z]/.test(value)
                      const hasSpecial = /[!@#$%^&*()_+\-=\[\]{};':"\\|,.<>\/?]/.test(value)
                    
                      const isValid = hasMin && hasCase && hasSpecial
                    
                      // ✅ IMPORTANT: criteria error clear karo
                      if (isValid && error === "Password does not meet the required criteria.") {
                        setError("")
                      }
                    
                      // match error bhi clear karo
                      if (confirmPassword && value === confirmPassword) {
                        setError("")
                      }
                    }}
                    required
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword((v) => !v)}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                  >
                    {showPassword ? <Eye size={18} /> : <EyeClosed size={18} />}
                  </button>
                </div>
                {showPasswordChecks ? <PasswordValidation password={password} onlyShowInvalid /> : null}
              </div>

              {/* Confirm Password */}
              <div className="grid gap-1.5">
                <Label htmlFor="confirm" className="text-sm font-medium">Confirm password</Label>
                <div className="relative">
                  <Input
                    id="confirm"
                    type={showConfirm ? "text" : "password"}
                    placeholder="Retype your password"
                    className="h-10 bg-background pr-10"
                    autoComplete="new-password"
                    value={confirmPassword}
                    onChange={(e) => {
                      const value = e.target.value
                      setConfirmPassword(value)
                    
                      // ✅ agar user edit kar raha hai → error hata do
                      if (!value || password === value) {
                        setError("")
                      }
                    }}
                    required
                  />
                  <button
                    type="button"
                    onClick={() => setShowConfirm((v) => !v)}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                  >
                    {showConfirm ? <Eye size={18} /> : <EyeClosed size={18} />}
                  </button>
                </div>
              </div>

              {error ? (
                <AuthAlert variant="error">{error}</AuthAlert>
              ) : null}

              {/* Submit */}
              <Button
                type="submit"
                disabled={true}
                className="mt-2 h-12 w-full rounded-[10px] bg-[#1F4ED8] hover:bg-[#1F4ED8]/90"
              >
                {loading ? "Please wait..." : "Continue →"}
              </Button>

              {/* Login CTA */}
              <div className="flex justify-center">
                <Button
                  variant="outline"
                  className="h-10 rounded-[10px] px-5 text-xs"
                  type="button"
                  onClick={() => navigate("/login")}
                >
                  <KeyRound className="mr-2 h-3.5 w-3.5" />
                  Already have an account?{" "}
                  <span className="ml-1 font-semibold text-[#1F4ED8]">Login</span>
                </Button>
              </div>
            </form>
          </div>
        </div>
      </div>
    </div>
  )
}