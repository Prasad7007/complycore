import { useState, useEffect } from "react"
import { createPortal } from "react-dom"
import { MainLayout } from "@/components/layout/MainLayout"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { PasswordUpdateSuccessModal } from "../components/models/PasswordUpdateSuccessModal"
import { PasswordValidation } from "@/components/auth/PasswordValidation"
import { Eye, EyeClosed ,ChevronDown} from "lucide-react"
import { apiFetch, documentsApi } from "@/lib/api"
import { cn } from "@/lib/utils"


type PermissionRow = { label: string; key: string; value: boolean }

const PERMISSION_LABELS: { key: string; label: string }[] = [
    { key: "canUploadDocuments", label: "Can upload documents" },
    { key: "canAssignReviewers", label: "Can assign reviewers" },
    { key: "canViewAIFlags", label: "Can view AI flags" },
    { key: "canAcceptAISuggestions", label: "Can accept AI suggestions" },
    { key: "canAddAlternateSuggestions", label: "Can add alternate suggestions" },
    { key: "canCommentOnFindings", label: "Can comment on AI findings" },
    { key: "canRejectAIFindings", label: "Can reject AI findings" },
    { key: "canApproveAtSMEStage", label: "Can approve at SME stage" },
    { key: "canRejectAtSMEStage", label: "Can reject at SME stage" },
    { key: "canRequestChangesAtSMEStage", label: "Can request changes at SME stage" },
    { key: "canApproveAtMarketingStage", label: "Can approve at marketing stage" },
    { key: "canApproveAtComplianceStage", label: "Can approve at compliance stage" },
    { key: "canRejectAtComplianceStage", label: "Can reject at compliance stage" },
    { key: "canRequestChangesAtComplianceStage", label: "Can request changes at compliance stage" },
    { key: "canLockDocument", label: "Can lock document" },
    { key: "canPublish", label: "Can publish documents" },
    { key: "canAccessAuditTrail", label: "Can access audit trail" },
    { key: "canExportReports", label: "Can export reports" },
    { key: "canAddComplianceNotes", label: "Can add compliance notes" },
    { key: "canManageSocialPosts", label: "Can manage social media posts" },
    { key: "canConfigureSocialSettings", label: "Can configure social media settings" },
    { key: "canManageUsers", label: "Can manage users" },
    { key: "canAssignRoles", label: "Can assign roles" },
]

const ROLE_PERMISSION_KEYS: Record<string, string[]> = {
    marketing: [
        "canUploadDocuments",
        "canAssignReviewers",
        "canViewAIFlags",
        "canAcceptAISuggestions",
        "canAddAlternateSuggestions",
        "canCommentOnFindings",
        "canApproveAtMarketingStage",
        "canPublish",
        "canAccessAuditTrail",
        "canExportReports",
        "canManageSocialPosts",
        "canConfigureSocialSettings",
    ],
    sme: [
        "canViewAIFlags",
        "canApproveAtSMEStage",
        "canRejectAtSMEStage",
        "canRequestChangesAtSMEStage",
        "canAccessAuditTrail",
        "canExportReports",
        "canManageSocialPosts",
    ],
    compliance: [
        "canViewAIFlags",
        "canAcceptAISuggestions",
        "canAddAlternateSuggestions",
        "canCommentOnFindings",
        "canRejectAIFindings",
        "canApproveAtComplianceStage",
        "canRejectAtComplianceStage",
        "canRequestChangesAtComplianceStage",
        "canLockDocument",
        "canAddComplianceNotes",
        "canAccessAuditTrail",
        "canExportReports",
        "canManageSocialPosts",
    ],
    super_admin: [
        "canUploadDocuments",
        "canAssignReviewers",
        "canViewAIFlags",
        "canAcceptAISuggestions",
        "canAddAlternateSuggestions",
        "canCommentOnFindings",
        "canApproveAtMarketingStage",
        "canPublish",
        "canAccessAuditTrail",
        "canExportReports",
        "canManageSocialPosts",
        "canConfigureSocialSettings",
        "canManageUsers",
        "canAssignRoles",
    ],
}

function buildPermissions(roles: string[]): PermissionRow[] {
    const granted = new Set<string>()
    for (const role of roles) {
        for (const key of ROLE_PERMISSION_KEYS[role] || []) {
            granted.add(key)
        }
    }
    return PERMISSION_LABELS.map((p) => ({ ...p, value: granted.has(p.key) }))
}

export default function UserProfilePage() {
    const [showChangePassword, setShowChangePassword] = useState(false)
    const [passwordStep, setPasswordStep] = useState<"form" | "success">("form")
    const [showCurrentPassword, setShowCurrentPassword] = useState(false)
    const [showNewPassword, setShowNewPassword] = useState(false)
    const [showConfirmPassword, setShowConfirmPassword] = useState(false)
    const [currentPassword, setCurrentPassword] = useState("")
    const [newPassword, setNewPassword] = useState("")
    const [confirmPassword, setConfirmPassword] = useState("")
    const [passwordError, setPasswordError] = useState("")
    const [isSubmitting, setIsSubmitting] = useState(false)
    const [hasTriedPasswordSubmit, setHasTriedPasswordSubmit] = useState(false)

    const hasMinLength = newPassword.length >= 8
    const hasMixedCase = /[A-Z]/.test(newPassword) && /[a-z]/.test(newPassword)
    const hasSpecialCharacter = /[!@#$%^&*()_+\-=\[\]{};':"\\|,.<>\/?]/.test(newPassword)
    const isPasswordCompliant = hasMinLength && hasMixedCase && hasSpecialCharacter
    const showPasswordChecks = newPassword.length > 0 && !isPasswordCompliant

    const [profile, setProfile] = useState<{
        id: string | null
        full_name: string
        email: string
        department: string
        phone_number: string | null
        roles: string[]
    } | null>(null)
    const [isEditing, setIsEditing] = useState(false)
    const [editForm, setEditForm] = useState({
        full_name: "",
        department: "",
        phone_number: "",
    })
    const [isSaving, setIsSaving] = useState(false)
    const [saveError, setSaveError] = useState("")
    const [permissions, setPermissions] = useState<PermissionRow[]>(buildPermissions([]))
    const [departmentOptions, setDepartmentOptions] = useState<string[]>([])

    const closePasswordModal = () => {
        setShowChangePassword(false)
        setPasswordStep("form")
        setCurrentPassword("")
        setNewPassword("")
        setConfirmPassword("")
        setPasswordError("")
        setHasTriedPasswordSubmit(false)
    }

    useEffect(() => {
        const loadProfileAndRoles = async () => {
            try {
                // Fetch profile and departments in parallel
                const [me, depts]: [any, any] = await Promise.all([
                    documentsApi.getUserInfo(),
                    apiFetch("/users/departments")
                ])

                const mappedProfile = {
                    id: me.id || null,
                    full_name: me.full_name || me.email || "User",
                    email: me.email || "",
                    department: me.department || "Unassigned",
                    phone_number: me.phone_number || "",
                    roles: Array.isArray(me.roles) ? me.roles : [],
                }
                setProfile(mappedProfile)
                setEditForm({
                    full_name: mappedProfile.full_name,
                    department: mappedProfile.department,
                    phone_number: mappedProfile.phone_number,
                })
                setPermissions(buildPermissions(mappedProfile.roles))

                if (Array.isArray(depts)) {
                    setDepartmentOptions(depts)
                }
            } catch (e) {
                console.error(e)
            }
        }
        loadProfileAndRoles()
    }, [])

    useEffect(() => {
        if (!showChangePassword) return
        const onKeyDown = (e: KeyboardEvent) => {
            if (e.key === "Escape") closePasswordModal()
        }
        window.addEventListener("keydown", onKeyDown)
        const prevOverflow = document.body.style.overflow
        document.body.style.overflow = "hidden"
        return () => {
            window.removeEventListener("keydown", onKeyDown)
            document.body.style.overflow = prevOverflow
        }
    }, [showChangePassword])

    useEffect(() => {
        if (!newPassword || !confirmPassword || newPassword === confirmPassword) {
          setPasswordError("")
        }
      }, [newPassword, confirmPassword])


      useEffect(() => {
        if (!currentPassword) {
          setPasswordError("")
        }
      }, [currentPassword])

    const handleSaveProfile = async () => {
        if (!profile?.id) return
        try {
            setIsSaving(true)
            setSaveError("")
            const updated: any = await apiFetch(`/users/${profile.id}/profile`, {
                method: "PUT",
                body: JSON.stringify(editForm)
            })
            setProfile({
                ...profile,
                full_name: updated.full_name,
                department: updated.department,
                phone_number: updated.phone_number
            })
            setIsEditing(false)

            // Force a full refresh so header/sidebar/dashboard user display picks up latest profile data.
            window.location.reload()
        } catch (err: any) {
            setSaveError(err.message || "Failed to save profile")
        } finally {
            setIsSaving(false)
        }
    }

    const handleCancelEdit = () => {
        if (profile) {
            setEditForm({
                full_name: profile.full_name,
                department: profile.department,
                phone_number: profile.phone_number || "",
            })
        }
        setIsEditing(false)
        setSaveError("")
    }

    return (
        <MainLayout
            header={{
                breadcrumbs: [
                    { label: "ComplyCore", to: "/dashboard/default" },
                    { label: "User Profile" },
                ],
            }}
        >
            <div className="w-full space-y-6">
                {/* Title - outside white box */}
                <div>
                    <h1 className="text-lg font-bold text-foreground">
                        Profile Information
                    </h1>
                    <p className="mt-0.5 text-sm text-muted-foreground">
                        Update your personal information and email address.
                    </p>
                </div>

                {/* Main card - contains everything else */}
                <div className="w-full rounded-xl border border-border bg-card px-6 pb-8 pt-6 shadow-sm dark:shadow-[-4px_4px_12px_rgba(0,0,0,0.3)] sm:px-10 sm:pb-10 sm:pt-8">

                    {/* Manage your profile - parent card header with Reset Password top-right */}
                    <div className="flex items-center justify-between gap-4">
                        <div className="flex items-center gap-2">
                            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-foreground/70"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
                            <span className="text-sm font-semibold text-foreground">
                                Manage your profile
                            </span>
                        </div>
                        <button
                            type="button"
                            onClick={() => setShowChangePassword(true)}
                            className="flex items-center gap-1.5 rounded-lg bg-[#174199] px-4 py-2 text-xs font-medium text-white shadow-sm hover:bg-[#174199]/90 transition-colors"
                            aria-label="Reset password"
                        >
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M2.586 17.414A2 2 0 0 0 2 18.828V21a1 1 0 0 0 1 1h3a1 1 0 0 0 1-1v-1a1 1 0 0 1 1-1h1a1 1 0 0 0 1-1v-1a1 1 0 0 1 1-1h.172a2 2 0 0 0 1.414-.586l.814-.814a6.5 6.5 0 1 0-4-4z"/><circle cx="16.5" cy="7.5" r=".5" fill="currentColor"/></svg>
                            Reset Password
                        </button>
                    </div>

                    {/* Profile area - avatar behind, gradient box in front */}
                    <div className="relative mx-auto mt-6 max-w-2xl">
                        {/* Large avatar - sits BEHIND the gradient box */}
                        <div className="flex justify-center">
                            <div className="relative z-0 h-40 w-40 overflow-hidden rounded-full border-4 border-white dark:border-card shadow-lg sm:h-48 sm:w-48">
                                <img
                                    src="/shared/default-avatar.png"
                                    alt="Profile avatar"
                                    className="h-full w-full object-cover"
                                />
                            </div>
                        </div>

                        {/* Gradient glassy box - sits ON TOP of the avatar */}
                        <div
                            className="relative z-10 -mt-8 rounded-2xl px-6 pb-6 pt-6 sm:-mt-10 sm:px-10 sm:pb-8 sm:pt-8 bg-[#5BC0EB66] dark:bg-[#1e3a5f66] backdrop-blur-[17.1px]"
                        >
                            {/* Edit button - top-right of blue child card, only for Super Admin */}
                            {profile?.roles?.includes("super_admin") && (
                                <button
                                    type="button"
                                    onClick={() => {
                                        if (isEditing) handleCancelEdit()
                                        else setIsEditing(true)
                                    }}
                                    className={cn(
                                        "absolute right-3 top-3 grid h-8 w-8 place-items-center rounded-full border border-white/40 shadow-sm backdrop-blur transition-colors sm:right-5 sm:top-5",
                                        isEditing 
                                            ? "bg-red-500/80 text-white border-red-400/50 hover:bg-red-500" 
                                            : "bg-white/70 text-muted-foreground hover:bg-white hover:text-foreground dark:border-border dark:bg-muted dark:hover:bg-accent/50"
                                    )}
                                    aria-label={isEditing ? "Cancel editing" : "Edit profile"}
                                >
                                    {isEditing ? (
                                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
                                    ) : (
                                        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" className="dark:invert dark:opacity-90">
                                            <rect width="24" height="24" rx="8" fill="#E3F5FF" />
                                            <path d="M16 11.4999L12.5 7.99994L14.1437 6.3562C14.1902 6.30896 14.2457 6.27142 14.3069 6.24585C14.368 6.22021 14.4337 6.20703 14.5 6.20703C14.5663 6.20703 14.632 6.22021 14.6931 6.24585C14.7543 6.27142 14.8098 6.30896 14.8563 6.3562L17.6437 9.14368C17.691 9.19025 17.7285 9.24567 17.7541 9.30682C17.7797 9.36798 17.7929 9.43365 17.7929 9.49994C17.7929 9.56622 17.7797 9.6319 17.7541 9.69305C17.7285 9.75421 17.691 9.80969 17.6437 9.8562L16 11.4999Z" fill="#1C1C1C" />
                                            <path d="M14.5 5.70703C14.5 5.70703 14.7006 5.70682 14.8857 5.78418C14.8857 5.78418 15.0719 5.86177 15.2129 6.00488L17.9971 8.79004C17.9971 8.79004 18.1372 8.92825 18.2148 9.11328C18.2148 9.11328 18.293 9.2991 18.293 9.5C18.293 9.50378 18.2916 9.70225 18.2148 9.88574C18.2148 9.88574 18.1382 10.0699 17.9971 10.21L10.3535 17.8535C10.2598 17.9473 10.1326 18 10 18H7C6.99816 18 6.58521 17.9992 6.29297 17.707C6.29297 17.707 6.00003 17.4142 6 17V14.2061C6 14.2001 6.00031 14.0073 6.07422 13.8271C6.07422 13.8271 6.14966 13.6442 6.28906 13.5039L13.79 6.00293C13.79 6.00293 13.9289 5.86177 14.1143 5.78418C14.1255 5.77955 14.3055 5.70703 14.5 5.70703ZM7 14.207V17H9.79297L17.293 9.5L14.5 6.70703L7 14.207Z" fill="#1C1C1C" />
                                            <path d="M15.6462 11.8533L15.6464 11.8536C15.7402 11.9473 15.8674 12 16 12C16.1326 12 16.2598 11.9473 16.3536 11.8536C16.4473 11.7598 16.5 11.6326 16.5 11.5C16.5 11.3674 16.4473 11.2402 16.3536 11.1464L16.3533 11.1462L12.8536 7.64651C12.7598 7.55268 12.6326 7.5 12.5 7.5C12.3674 7.5 12.2402 7.55268 12.1464 7.64645C12.0527 7.74021 12 7.86739 12 8C12 8.13261 12.0527 8.25979 12.1464 8.35355L15.6462 11.8533Z" fill="#1C1C1C" />
                                            <path d="M17.5 17H10C9.72386 17 9.5 17.2239 9.5 17.5C9.5 17.7761 9.72386 18 10 18H17.5C17.7761 18 18 17.7761 18 17.5C18 17.2239 17.7761 17 17.5 17Z" fill="#1C1C1C" />
                                        </svg>
                                    )}
                                </button>
                            )}

                            {/* Current Role badge */}
                            <div className="flex justify-center">
                                <div className="rounded-xl border border-white/60 bg-white dark:border-border dark:bg-muted px-6 py-2.5 text-center shadow-sm backdrop-blur">
                                    <div className="text-[11px] text-muted-foreground">{(profile?.roles?.length ?? 0) > 1 ? "Current Roles" : "Current Role"}</div>
                                    <div className="mt-0.5 flex flex-wrap justify-center gap-1 text-sm font-bold text-foreground">
                                        {profile?.roles && profile.roles.length > 0
                                            ? profile.roles.map((r: string) => {
                                                const label =
                                                    r === "marketing" ? "Marketing" :
                                                    r === "sme" ? "SME Reviewer" :
                                                    r === "compliance" ? "Compliance" :
                                                    r === "super_admin" ? "Super Admin" : r
                                                return <span key={r} className="rounded-md bg-blue-50 dark:bg-blue-950/50 px-2 py-0.5 text-xs font-medium text-blue-600 dark:text-blue-400">{label}</span>
                                            })
                                            : <span>User</span>
                                        }
                                    </div>
                                </div>
                            </div>

                            {/* Full Name, Department, Mobile, Email - INSIDE gradient box */}
                            <div className="mt-5 grid grid-cols-1 gap-4 sm:grid-cols-2">
                                <div className="rounded-xl border border-white/60 bg-white dark:border-border dark:bg-muted px-5 py-4 backdrop-blur">
                                    <div className="text-xs text-muted-foreground">Full Name</div>
                                    <div className="mt-1 text-sm font-medium text-foreground">
                                        {isEditing ? (
                                            <input
                                                className="w-full bg-transparent outline-none border-b border-blue-400 focus:border-blue-600"
                                                value={editForm.full_name}
                                                onChange={(e) => setEditForm(s => ({ ...s, full_name: e.target.value }))}
                                            />
                                        ) : (
                                            profile?.full_name || "-"
                                        )}
                                    </div>
                                </div>
                                <div className="rounded-xl border border-white/60 bg-white dark:border-border dark:bg-muted px-5 py-4 backdrop-blur">
                                    <div className="text-xs text-muted-foreground">Department</div>
                                    <div className="mt-1 text-sm font-medium text-foreground">
                                        {isEditing ? (
                                            <div className="relative">
                                                <select
                                                    className="w-full appearance-none bg-transparent outline-none border-b border-blue-400 focus:border-blue-600 pr-8 cursor-pointer"
                                                    value={editForm.department}
                                                    onChange={(e) => setEditForm(s => ({ ...s, department: e.target.value }))}
                                                >
                                                    <option value="" disabled className="dark:bg-muted">Select Department</option>
                                                    {departmentOptions.map(opt => (
                                                        <option key={opt} value={opt} className="dark:bg-muted font-normal">
                                                            {opt}
                                                        </option>
                                                    ))}
                                                </select>
                                                <ChevronDown className="pointer-events-none absolute right-0 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground/60" />
                                            </div>
                                        ) : (
                                            profile?.department || "-"
                                        )}
                                    </div>
                                </div>
                            </div>
                            <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
                                <div className="rounded-xl border border-white/60 bg-white dark:border-border dark:bg-muted px-5 py-4 backdrop-blur">
                                    <div className="text-xs text-muted-foreground">Mobile</div>
                                    <div className="mt-1 text-sm font-medium text-foreground">
                                        {isEditing ? (
                                            <input
                                                className="w-full bg-transparent outline-none border-b border-blue-400 focus:border-blue-600"
                                                value={editForm.phone_number}
                                                onChange={(e) => setEditForm(s => ({ ...s, phone_number: e.target.value }))}
                                                placeholder="Enter phone number"
                                            />
                                        ) : (
                                            profile?.phone_number || "—"
                                        )}
                                    </div>
                                </div>
                                <div className="rounded-xl border border-white/60 bg-white dark:border-border dark:bg-muted px-5 py-4 backdrop-blur">
                                    <div className="text-xs text-muted-foreground">Email Address</div>
                                    <div className="mt-1 text-sm font-medium text-foreground">
                                        {profile?.email || "-"}
                                    </div>
                                </div>
                            </div>

                            {isEditing && (
                                <div className="mt-6 flex flex-col gap-3">
                                    {saveError && (
                                        <p className="text-center text-xs text-red-500 font-medium">
                                            {saveError}
                                        </p>
                                    )}
                                    <button
                                        type="button"
                                        disabled={isSaving}
                                        onClick={handleSaveProfile}
                                        className="h-10 w-full rounded-xl bg-[#174199] text-sm font-semibold text-white shadow-lg hover:bg-[#174199]/90 disabled:opacity-50 transition-all active:scale-[0.98]"
                                    >
                                        {isSaving ? "Saving..." : "Save Changes"}
                                    </button>
                                </div>
                            )}
                        </div>
                    </div>

                    {/* Permissions section - inside white box */}
                    {/*
                    <div className="mt-8">
                        <h2 className="text-sm font-bold text-foreground">
                            Your Permissions
                        </h2>
                        <p className="mt-0.5 text-xs text-muted-foreground">
                            Based on your assigned role{(profile?.roles?.length ?? 0) > 1 ? "s" : ""}: {profile?.roles?.map((r) => {
                                const label =
                                    r === "marketing" ? "Marketing" :
                                    r === "sme" ? "SME Reviewer" :
                                    r === "compliance" ? "Compliance" :
                                    r === "super_admin" ? "Super Admin" : r
                                return label
                            }).join(", ") || "None"}
                        </p>

                        <div className="mt-4 grid grid-cols-1 gap-x-12 gap-y-2 sm:grid-cols-2">
                            {permissions.map((p) => (
                                <div key={p.key} className="flex items-center gap-2 text-sm">
                                    {p.value ? (
                                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" className="shrink-0 text-emerald-500"><path d="M20 6 9 17l-5-5"/></svg>
                                    ) : (
                                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" className="shrink-0 text-red-400"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
                                    )}
                                    <span className={p.value ? "text-foreground" : "text-muted-foreground"}>
                                        {p.label}
                                    </span>
                                </div>
                            ))}
                        </div>
                    </div>
                    */}
                </div>
            </div>

            {/* Change Password Modal - blurred backdrop, centered card (form only) */}
            {showChangePassword && passwordStep === "form" && typeof document !== "undefined" && createPortal(
                <div
                    className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/30 backdrop-blur-md px-4"
                    role="dialog"
                    aria-modal="true"
                    aria-label="Change password"
                    onMouseDown={(e) => {
                        if (e.target === e.currentTarget) closePasswordModal()
                    }}
                >
                    <div
                        className="w-full max-w-md rounded-xl border border-border bg-card shadow-[0_24px_80px_rgba(16,24,40,0.25)] dark:shadow-[0_24px_80px_rgba(0,0,0,0.45)] px-6 pt-6 pb-6"
                        onMouseDown={(e) => e.stopPropagation()}
                    >
                        <>
                        <h2 className="text-base font-semibold text-foreground">
                            Update Your Password
                        </h2>
                        <p className="mt-1 text-xs text-muted-foreground">
                            Enter your current password and choose a new one.
                        </p>
                        {passwordError && (
                            <div className="mt-4 rounded-md bg-red-500/20 p-3 text-sm text-destructive border border-red-500/50">
                                {passwordError}
                            </div>
                        )}
                        <form
                            className="mt-6 flex flex-col gap-5"
                            onSubmit={async (e) => {
                                e.preventDefault()
                                setPasswordError("")
                                setHasTriedPasswordSubmit(true)
                                if (!isPasswordCompliant) {
                                    setPasswordError("Password does not meet the required criteria.")
                                    return
                                }
                                if (currentPassword === newPassword) {
                                    setPasswordError("New password cannot be the same as your current password.")
                                    return
                                }
                                if (newPassword !== confirmPassword) {
                                    setPasswordError("Passwords do not match.")
                                    return
                                }
                                try {
                                    setIsSubmitting(true)
                                    await apiFetch("/auth/change-password", {
                                        method: "POST",
                                        body: JSON.stringify({
                                            old_password: currentPassword,
                                            new_password: newPassword
                                        })
                                    })
                                    setPasswordStep("success")
                                } catch (err: any) {
                                    setPasswordError(err.message || "Failed to update password.")
                                } finally {
                                    setIsSubmitting(false)
                                }
                            }}
                        >
                            {/* Current Password */}
                            <div className="flex flex-col gap-1.5">
                                <Label htmlFor="modal-current-password" className="text-sm font-semibold text-foreground">
                                    Current Password
                                </Label>
                                <div className="relative">
                                    <Input
                                        id="modal-current-password"
                                        type={showCurrentPassword ? "text" : "password"}
                                        value={currentPassword}
                                        onChange={(e) => {
  const value = e.target.value
  setCurrentPassword(value)

  // 👇 CLEAR error when typing or clearing
  if (!value) {
    setPasswordError("")
  }
}}
                                        placeholder="Enter current password"
                                        autoComplete="current-password"
                                        className="h-11 rounded-lg border border-input bg-background px-3 pr-10 text-sm text-foreground placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-[#128BDA]/30"
                                    />
                                    <button
                                        type="button"
                                        onClick={() => setShowCurrentPassword((v) => !v)}
                                        className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                                        aria-label={showCurrentPassword ? "Hide password" : "Show password"}
                                    >
                                        {showCurrentPassword ? <Eye size={17} /> : <EyeClosed size={17} />}
                                    </button>
                                </div>
                            </div>

                            {/* New Password */}
                            <div className="flex flex-col gap-1.5">
                                <Label htmlFor="modal-new-password" className="text-sm font-semibold text-foreground">
                                    New Password
                                </Label>
                                <div className="relative">
                                    <Input
                                        id="modal-new-password"
                                        type={showNewPassword ? "text" : "password"}
                                        value={newPassword}
                                        onChange={(e) => {
                                            const value = e.target.value
                                            setNewPassword(value)
                                          
                                            // 👇 CLEAR ERROR when typing or clearing
                                            if (!value || value === confirmPassword) {
                                              setPasswordError("")
                                            }
                                          }}
                                        placeholder="Enter new password"
                                        autoComplete="new-password"
                                        className="h-11 rounded-lg border border-input bg-background px-3 pr-10 text-sm text-foreground placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-[#128BDA]/30"
                                    />
                                    <button
                                        type="button"
                                        onClick={() => setShowNewPassword((v) => !v)}
                                        className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                                        aria-label={showNewPassword ? "Hide password" : "Show password"}
                                    >
                                        {showNewPassword ? <Eye size={17} /> : <EyeClosed size={17} />}
                                    </button>
                                </div>
                                {showPasswordChecks ? (
                                    <div className="text-muted-foreground">
                                        <PasswordValidation password={newPassword} onlyShowInvalid />
                                    </div>
                                ) : null}
                            </div>

                            {/* Confirm New Password */}
                            <div className="flex flex-col gap-1.5">
                                <Label htmlFor="modal-confirm-password" className="text-sm font-semibold text-foreground">
                                    Confirm New Password
                                </Label>
                                <div className="relative">
                                    <Input
                                        id="modal-confirm-password"
                                        type={showConfirmPassword ? "text" : "password"}
                                        value={confirmPassword}
                                        onChange={(e) => {
                                            const nextConfirmPassword = e.target.value
                                            setConfirmPassword(nextConfirmPassword)
                                            if (passwordError === "Passwords do not match." && newPassword === nextConfirmPassword) {
                                                setPasswordError("")
                                            }
                                        }}
                                        placeholder="Re-enter new password"
                                        autoComplete="new-password"
                                        className="h-11 rounded-lg border border-input bg-background px-3 pr-10 text-sm text-foreground placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-[#128BDA]/30"
                                    />
                                    <button
                                        type="button"
                                        onClick={() => setShowConfirmPassword((v) => !v)}
                                        className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                                        aria-label={showConfirmPassword ? "Hide password" : "Show password"}
                                    >
                                        {showConfirmPassword ? <Eye size={17} /> : <EyeClosed size={17} />}
                                    </button>
                                </div>
                            </div>

                            {/* Actions */}
                            <div className="mt-2 flex flex-col gap-4">
                                <button
                                    type="submit"
                                    disabled={isSubmitting}
                                    className="flex h-12 w-full items-center justify-center gap-2 rounded-lg bg-[#174199] text-sm font-semibold text-white hover:bg-[#174199]/90 transition-colors disabled:opacity-50"
                                >
                                    {isSubmitting ? "Resetting..." : "Reset Password"}
                                    {!isSubmitting && <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="5" y1="12" x2="19" y2="12"/><polyline points="12 5 19 12 12 19"/></svg>}
                                </button>
                                <button
                                    type="button"
                                    onClick={closePasswordModal}
                                    disabled={isSubmitting}
                                    className="h-9 rounded-lg bg-transparent px-5 text-xs font-medium text-muted-foreground underline hover:text-foreground disabled:opacity-50"
                                >
                                    Cancel
                                </button>
                            </div>
                        </form>
                        </>
                    </div>
                </div>,
                document.body
            )}

            {/* Success Modal - Figma design */}
            <PasswordUpdateSuccessModal
                open={showChangePassword && passwordStep === "success"}
                onClose={closePasswordModal}
            />
        </MainLayout>
    )
}