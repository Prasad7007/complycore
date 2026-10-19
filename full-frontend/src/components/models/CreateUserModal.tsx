import * as React from "react"
import { createPortal } from "react-dom"
import { Eye, ChevronDown, X } from "lucide-react"
import { apiFetch } from "@/lib/api"
import { PasswordValidation } from "@/components/auth/PasswordValidation"
import { ConfirmationModal } from "./ConfirmationModal"

const inputBaseStyles = {
    width: "100%",
    height: "40px",
    borderRadius: "8px",
    fontFamily: "Inter, sans-serif",
    fontSize: "14px",
    padding: "0 16px",
} as const

const focusStyles = "focus:border-[#128BDA] focus:outline-none focus:ring-1 focus:ring-[#128BDA]/30"

export type NewUserData = {
    fullName: string
    email: string
    department: string
    roles: string[]
    password?: string
}

export type CreateUserModalProps = {
    onClose: () => void
    /** Request OTP to super admin email; return session id from API */
    onChallenge: (data: NewUserData) => Promise<string>
    /** Complete provisioning after OTP verified */
    onConfirm: (session: string, otp: string) => Promise<void>
    onResend?: (session: string) => Promise<void>
}

export function CreateUserModal({ onClose, onChallenge, onConfirm, onResend }: CreateUserModalProps) {
    const [step, setStep] = React.useState<"form" | "otp">("form")
    const [fullName, setFullName] = React.useState("")
    const [email, setEmail] = React.useState("")
    const [department, setDepartment] = React.useState("")
    const [selectedRoles, setSelectedRoles] = React.useState<string[]>([])
    const [password, setPassword] = React.useState("")
    const [showPassword, setShowPassword] = React.useState(false)
    const [hasTriedSubmit, setHasTriedSubmit] = React.useState(false)
    const [showSuperAdminWarning, setShowSuperAdminWarning] = React.useState(false)

    const hasMinLength = password.length >= 8
    const hasMixedCase = /[A-Z]/.test(password) && /[a-z]/.test(password)
    const hasSpecialCharacter = /[!@#$%^&*()_+\-=\[\]{};':"\\|,.<>\/?]/.test(password)
    const isPasswordCompliant = hasMinLength && hasMixedCase && hasSpecialCharacter
    const showPasswordChecks = hasTriedSubmit && !isPasswordCompliant

    const [challengeSession, setChallengeSession] = React.useState<string | null>(null)
    const [otp, setOtp] = React.useState("")
    const [busy, setBusy] = React.useState(false)
    const [error, setError] = React.useState<string | null>(null)

    const [departmentOptions, setDepartmentOptions] = React.useState<string[]>([])
    const [roleOptions, setRoleOptions] = React.useState<{ name: string; display_name: string }[]>([])

    const withMarketingDepartment = React.useCallback((list: string[]) => {
        const normalized = Array.from(
            new Set(
                list
                    .map((d) => d?.trim())
                    .filter((d): d is string => Boolean(d))
            )
        )
        const hasMarketing = normalized.some((d) => d.toLowerCase() === "marketing")
        return hasMarketing ? normalized : [...normalized, "Marketing"]
    }, [])

    const resetFormFields = () => {
        setFullName("")
        setEmail("")
        setDepartment("")
        setSelectedRoles([])
        setPassword("")
        setHasTriedSubmit(false)
        setOtp("")
        setChallengeSession(null)
        setStep("form")
        setError(null)
    }

    React.useEffect(() => {
        const loadOptions = async () => {
            try {
                const [depts, roles]: [any, any] = await Promise.all([
                    apiFetch("/users/departments"),
                    apiFetch("/roles")
                ])
                if (Array.isArray(depts)) setDepartmentOptions(withMarketingDepartment(depts))
                else setDepartmentOptions(withMarketingDepartment([]))
                if (Array.isArray(roles)) {
                    setRoleOptions(
                        roles.filter((r: { name?: string }) => String(r?.name || "") !== "owner")
                    )
                }
            } catch (e) {
                console.error("Failed to load user options:", e)
                setDepartmentOptions(withMarketingDepartment([]))
            }
        }
        loadOptions()

        const onKeyDown = (e: KeyboardEvent) => {
            if (e.key === "Escape") onClose()
        }
        window.addEventListener("keydown", onKeyDown)
        const prevOverflow = document.body.style.overflow
        document.body.style.overflow = "hidden"
        return () => {
            window.removeEventListener("keydown", onKeyDown)
            document.body.style.overflow = prevOverflow
        }
    }, [onClose])

    const handleClose = () => {
        resetFormFields()
        onClose()
    }

    const handleFormSubmit = async (e: React.FormEvent) => {
        e.preventDefault()
        setError(null)
        setHasTriedSubmit(true)
        const pwd = password.trim()
        if (!hasMinLength || !hasMixedCase || !hasSpecialCharacter) {
            setError("Password does not meet the required criteria.")
            return
        }
        if (!fullName.trim() || !email.trim() || !department || selectedRoles.length === 0) {
            setError("Please fill in all required fields.")
            return
        }

        const data: NewUserData = {
            fullName: fullName.trim(),
            email: email.trim(),
            department,
            roles: [...selectedRoles],
            password: pwd,
        }

        if (selectedRoles.includes("super_admin") && !showSuperAdminWarning) {
            setShowSuperAdminWarning(true)
            return
        }

        await proceedWithChallenge(data)
    }

    const proceedWithChallenge = async (data: NewUserData) => {
        setBusy(true)
        try {
            const session = await onChallenge(data)
            setChallengeSession(session)
            setOtp("")
            setStep("otp")
            setShowSuperAdminWarning(false)
        } catch (err: unknown) {
            const msg = err instanceof Error ? err.message : "Failed to send verification code."
            setError(msg)
            setShowSuperAdminWarning(false)
        } finally {
            setBusy(false)
        }
    }

    const handleOtpSubmit = async (e: React.FormEvent) => {
        e.preventDefault()
        if (!challengeSession) {
            setError("Session expired. Start over.")
            return
        }
        const code = otp.replace(/\D/g, "").slice(0, 6)
        if (code.length !== 6) {
            setError("Enter the 6-digit code.")
            return
        }
        setBusy(true)
        setError(null)
        try {
            await onConfirm(challengeSession, code)
            resetFormFields()
            onClose()
        } catch (err: unknown) {
            const msg = err instanceof Error ? err.message : "Verification failed."
            setError(msg)
        } finally {
            setBusy(false)
        }
    }

    const handleResend = async () => {
        if (!challengeSession || !onResend) return
        setBusy(true)
        setError(null)
        try {
            await onResend(challengeSession)
        } catch (err: unknown) {
            const msg = err instanceof Error ? err.message : "Could not resend code."
            setError(msg)
        } finally {
            setBusy(false)
        }
    }

    if (typeof document === "undefined") return null

    return createPortal(
        <div
            className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/20 backdrop-blur-md"
            role="dialog"
            aria-modal="true"
            aria-label={step === "form" ? "Create User" : "Verify administrator code"}
            onMouseDown={(e) => {
                if (e.target === e.currentTarget) handleClose()
            }}
        >
            <div
                className="mx-4 flex min-h-[520px] w-[570px] max-w-[calc(100vw-32px)] flex-col rounded-2xl border border-border bg-card p-4 shadow-[0_24px_80px_rgba(16,24,40,0.25)] dark:bg-gradient-to-br dark:from-[#1e3a5f] dark:to-[#312e81] dark:backdrop-blur-[20px] dark:shadow-[0_0_50px_rgba(30,58,95,0.4),0_25px_50px_-12px_rgba(0,0,0,0.5)]"
            >
                <div className="flex items-start justify-between">
                    <h2
                        className="text-[20px] font-semibold leading-[36px] text-foreground"
                        style={{ fontFamily: "Inter, sans-serif" }}
                    >
                        {step === "form" ? "Create User" : "Verify it’s you"}
                    </h2>
                    <button
                        type="button"
                        onClick={handleClose}
                        className="grid h-8 w-8 shrink-0 place-items-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground"
                        style={{ width: "32px", height: "32px" }}
                        aria-label="Close"
                    >
                        <X className="h-5 w-5" strokeWidth={2} />
                    </button>
                </div>

                {step === "form" ? (
                    <form className="mt-6 flex flex-1 flex-col " onSubmit={handleFormSubmit}>
                        {error ? (
                            <p className="mb-3 text-sm text-red-600 dark:text-red-400" role="alert">
                                {error}
                            </p>
                        ) : null}
                        <div className="flex flex-col items-center gap-4">
                            <div className="flex w-[425px] max-w-full flex-col">
                                <label
                                    className="mb-1 block text-sm font-medium text-foreground"
                                    style={{ fontFamily: "Inter, sans-serif" }}
                                >
                                    Full Name
                                </label>
                                <input
                                    type="text"
                                    placeholder="Your name"
                                    value={fullName}
                                    onChange={(e) => setFullName(e.target.value)}
                                    className={`${focusStyles} border border-input bg-background text-foreground placeholder:text-muted-foreground`}
                                    style={inputBaseStyles}
                                />
                            </div>

                            <div className="flex w-[425px] max-w-full flex-col">
                                <label
                                    className="mb-1 block text-sm font-medium text-foreground"
                                    style={{ fontFamily: "Inter, sans-serif" }}
                                >
                                    Email Address
                                </label>
                                <input
                                    type="email"
                                    placeholder="Your official email"
                                    value={email}
                                    onChange={(e) => setEmail(e.target.value)}
                                    className={`${focusStyles} border border-input bg-background text-foreground placeholder:text-muted-foreground`}
                                    style={inputBaseStyles}
                                />
                            </div>

                            <div className="flex w-[425px] max-w-full flex-col">
                                <label
                                    className="mb-1 block text-sm font-medium text-foreground"
                                    style={{ fontFamily: "Inter, sans-serif" }}
                                >
                                    Department
                                </label>
                                <div className="relative w-full overflow-hidden rounded-lg border border-input bg-background focus-within:border-[#128BDA] focus-within:ring-1 focus-within:ring-[#128BDA]/30 dark:border-border">
                                    <select
                                        value={department}
                                        onChange={(e) => setDepartment(e.target.value)}
                                        className={`w-full appearance-none border-0 bg-transparent py-0 pr-10 ${focusStyles} focus:ring-0`}
                                        style={{
                                            height: "40px",
                                            paddingLeft: "16px",
                                            fontFamily: "Inter, sans-serif",
                                            fontSize: "14px",
                                            color: department ? "inherit" : "rgba(156, 163, 175, 1)",
                                        }}
                                    >
                                        <option value="">Select</option>
                                        {departmentOptions.map((d: string) => (
                                            <option key={d} value={d}>
                                                {d}
                                            </option>
                                        ))}
                                    </select>
                                    <ChevronDown
                                        className="pointer-events-none absolute right-4 top-1/2 h-5 w-5 -translate-y-1/2 text-muted-foreground"
                                        strokeWidth={2}
                                    />
                                </div>
                            </div>

                            <div className="flex w-[425px] max-w-full flex-col">
                                <label
                                    className="mb-1 block text-sm font-medium text-foreground"
                                    style={{ fontFamily: "Inter, sans-serif" }}
                                >
                                    Roles
                                </label>
                                <p
                                    className="mb-2 text-xs text-muted-foreground"
                                    style={{ fontFamily: "Inter, sans-serif" }}
                                >
                                    Select a role for this user.
                                </p>
                                <div
                                    className={`max-h-[200px] overflow-y-auto rounded-lg border border-input bg-background px-3 py-2 dark:border-border ${
                                        hasTriedSubmit && selectedRoles.length === 0
                                            ? "ring-1 ring-red-500/40"
                                            : "focus-within:border-[#128BDA] focus-within:ring-1 focus-within:ring-[#128BDA]/30"
                                    }`}
                                    role="group"
                                    aria-label="Roles"
                                >
                                    <ul className="flex flex-col gap-2">
                                        {roleOptions.map((r: { name: string; display_name: string }) => {
                                            const checked = selectedRoles.includes(r.name)
                                            const hasSuperAdmin = selectedRoles.includes("super_admin")
                                            const isSuperAdminRole = r.name === "super_admin"

                                            // Disabled if not checked, and:
                                            // 1. We already have 2 roles selected.
                                            // 2. We have 1 role selected, and neither the selected role nor this role is super_admin.
                                            const isDisabled = !checked && (
                                                selectedRoles.length >= 2 ||
                                                (selectedRoles.length === 1 && !hasSuperAdmin && !isSuperAdminRole)
                                            )

                                            return (
                                                <li key={r.name}>
                                                    <label className={`flex cursor-pointer items-start gap-2 text-sm text-foreground ${isDisabled ? 'opacity-50 cursor-not-allowed' : ''}`}>
                                                        <input
                                                            type="checkbox"
                                                            checked={checked}
                                                            disabled={isDisabled}
                                                            onChange={() => {
                                                                setSelectedRoles((prev) => {
                                                                    if (prev.includes(r.name)) {
                                                                        return prev.filter((x) => x !== r.name)
                                                                    } else {
                                                                        return [...prev, r.name]
                                                                    }
                                                                })
                                                            }}
                                                            className="mt-0.5 h-4 w-4 shrink-0 rounded border-input text-[#128BDA] focus:ring-[#128BDA] disabled:cursor-not-allowed"
                                                        />
                                                        <span style={{ fontFamily: "Inter, sans-serif" }}>
                                                            {r.display_name || r.name}
                                                        </span>
                                                    </label>
                                                </li>
                                            )
                                        })}
                                    </ul>
                                </div>
                            </div>

                            <div className="flex w-[425px] max-w-full flex-col">
                                <label
                                    className="mb-1 block text-sm font-medium text-foreground"
                                    style={{ fontFamily: "Inter, sans-serif" }}
                                >
                                    Temporary Password
                                </label>
                                <div className="relative w-full overflow-hidden rounded-lg border border-input bg-background focus-within:border-[#128BDA] focus-within:ring-1 focus-within:ring-[#128BDA]/30 dark:border-border">
                                    <input
                                        type={showPassword ? "text" : "password"}
                                        placeholder="Your Password"
                                        value={password}
                                        onChange={(e) => setPassword(e.target.value)}
                                        className={`w-full border-0 bg-transparent py-0 pr-12 text-foreground focus:ring-0 ${focusStyles} placeholder:text-muted-foreground`}
                                        style={{
                                            height: "40px",
                                            paddingLeft: "16px",
                                            fontFamily: "Inter, sans-serif",
                                            fontSize: "14px",
                                        }}
                                    />
                                    <button
                                        type="button"
                                        onClick={() => setShowPassword(!showPassword)}
                                        className="absolute right-4 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                                        aria-label={showPassword ? "Hide password" : "Show password"}
                                    >
                                        {showPassword ? (
                                            <Eye className="h-5 w-5" strokeWidth={2} />
                                        ) : (
                                            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M9.88 9.88a3 3 0 1 0 4.24 4.24"/><path d="M10.73 5.08A10.43 10.43 0 0 1 12 5c7 0 10 7 10 7a13.16 13.16 0 0 1-1.67 2.68"/><path d="M6.61 6.61A13.526 13.526 0 0 0 2 12s3 7 10 7a9.74 9.74 0 0 0 5.39-1.61"/><line x1="2" y1="2" x2="22" y2="22"/></svg>
                                        )}
                                    </button>
                                </div>
                                {showPasswordChecks ? (
                                    <div className="mt-2">
                                        <PasswordValidation password={password} onlyShowInvalid />
                                    </div>
                                ) : null}
                            </div>
                        </div>

                        <div className="mt-6 flex w-full justify-end" style={{ gap: "12px" }}>
                            <button
                                type="button"
                                onClick={handleClose}
                                className="h-[38px] w-[124px] shrink-0 rounded-lg border border-border bg-transparent text-[14px] font-normal text-foreground hover:bg-muted"
                                style={{
                                    fontFamily: "Inter, sans-serif",
                                }}
                            >
                                Cancel
                            </button>
                            <button
                                type="submit"
                                disabled={busy}
                                className="h-[38px] min-w-[114px] shrink-0 rounded-lg text-[14px] font-medium text-white hover:opacity-90 disabled:opacity-50"
                                style={{
                                    backgroundColor: "#128BDA",
                                    fontFamily: "Inter, sans-serif",
                                }}
                            >
                                {busy ? "Sending…" : "Continue"}
                            </button>
                        </div>
                    </form>
                ) : (
                    <form className="mt-6 flex flex-1 flex-col" onSubmit={handleOtpSubmit}>
                        <p
                            className="mb-4 text-sm text-muted-foreground"
                            style={{ fontFamily: "Inter, sans-serif" }}
                        >
                            Enter the verification code sent to your administrator email to confirm creating this
                            account.
                        </p>
                        {error ? (
                            <p className="mb-3 text-sm text-red-600 dark:text-red-400" role="alert">
                                {error}
                            </p>
                        ) : null}
                        <div className="flex w-[425px] max-w-full flex-col">
                            <label
                                className="mb-1 block text-sm font-medium text-foreground"
                                style={{ fontFamily: "Inter, sans-serif" }}
                            >
                                Verification code
                            </label>
                            <input
                                type="text"
                                inputMode="numeric"
                                autoComplete="one-time-code"
                                placeholder="000000"
                                maxLength={6}
                                value={otp}
                                onChange={(e) => setOtp(e.target.value.replace(/\D/g, "").slice(0, 6))}
                                className={`${focusStyles} border border-input bg-background text-foreground placeholder:text-muted-foreground tracking-widest`}
                                style={inputBaseStyles}
                            />
                        </div>

                        <div className="mt-6 flex w-full flex-wrap items-center justify-between gap-3">
                            <button
                                type="button"
                                onClick={() => {
                                    setStep("form")
                                    setChallengeSession(null)
                                    setOtp("")
                                    setError(null)
                                }}
                                className="text-sm text-muted-foreground underline hover:text-foreground"
                                style={{ fontFamily: "Inter, sans-serif" }}
                            >
                                Back
                            </button>
                            {onResend ? (
                                <button
                                    type="button"
                                    disabled={busy}
                                    onClick={handleResend}
                                    className="text-sm font-medium text-[#128BDA] hover:underline disabled:opacity-50"
                                    style={{ fontFamily: "Inter, sans-serif" }}
                                >
                                    Resend code
                                </button>
                            ) : null}
                        </div>

                        <div className="mt-6 flex w-full justify-end" style={{ gap: "12px" }}>
                            <button
                                type="button"
                                onClick={handleClose}
                                className="h-[38px] w-[124px] shrink-0 rounded-lg border border-border bg-transparent text-[14px] font-normal text-foreground hover:bg-muted"
                                style={{
                                    fontFamily: "Inter, sans-serif",
                                }}
                            >
                                Cancel
                            </button>
                            <button
                                type="submit"
                                disabled={busy}
                                className="h-[38px] min-w-[120px] shrink-0 rounded-lg text-[14px] font-medium text-white hover:opacity-90 disabled:opacity-50"
                                style={{
                                    backgroundColor: "#128BDA",
                                    fontFamily: "Inter, sans-serif",
                                }}
                            >
                                {busy ? "Verifying…" : "Create user"}
                            </button>
                        </div>
                    </form>
                )}
            </div>
            
            <ConfirmationModal
                isOpen={showSuperAdminWarning}
                title="Create Super Admin"
                message="You are about to create a new Super Admin. This user will have full access to manage the platform and its users. Are you sure you want to proceed?"
                confirmText="Yes, create Super Admin"
                cancelText="No, cancel"
                isDanger={true}
                onCancel={() => setShowSuperAdminWarning(false)}
                onConfirm={() => {
                    const pwd = password.trim()
                    const data: NewUserData = {
                        fullName: fullName.trim(),
                        email: email.trim(),
                        department,
                        roles: [...selectedRoles],
                        password: pwd,
                    }
                    proceedWithChallenge(data)
                }}
            />
        </div>,
        document.body
    )
}
