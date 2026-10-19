import * as React from "react"
import { MainLayout } from "@/components/layout/MainLayout"
import { CreateUserModal, type NewUserData } from "../components/models/CreateUserModal"
import { ConfirmationModal } from "../components/models/ConfirmationModal"
import { X } from "lucide-react"
import { apiFetch, documentsApi, invalidateUserMeCache } from "@/lib/api"
import { Label } from "@/components/ui/label"

type UserRow = {
    id: string
    name: string
    email: string
    department: string
    role: string
    roles: string[]
    roleColor: "blue" | "orange" | "teal" | "red"
    assignedDate: string
    status: "Active" | "Inactive"
}

type RoleOption = {
    id: string
    name: string
    display_name?: string
}

const PAGE_SIZE = 15

const roleBadgeStyles: Record<string, string> = {
    blue: "border-blue-400 text-blue-600 bg-blue-50 dark:border-blue-600 dark:bg-blue-950/50 dark:text-blue-400",
    orange: "border-orange-400 text-orange-600 bg-orange-50 dark:border-orange-600 dark:bg-orange-950/50 dark:text-orange-400",
    teal: "border-teal-400 text-teal-600 bg-teal-50 dark:border-teal-600 dark:bg-teal-950/50 dark:text-teal-400",
    red: "border-red-400 text-red-600 bg-red-50 dark:border-red-600 dark:bg-red-950/50 dark:text-red-400",
}

const roleToColor: Record<string, "blue" | "orange" | "teal" | "red"> = {
    "Marketing": "blue",
    "SME Reviewer": "orange",
    "Compliance": "red",
    "Super Admin": "blue",
}

const ROLE_KEY_ORDER = ["super_admin", "compliance", "marketing", "sme"]
const HIDDEN_ROLE_KEYS = new Set(["owner"])

function roleKeyToDisplay(key: string): string {
    const map: Record<string, string> = {
        marketing: "Marketing",
        sme: "SME Reviewer",
        compliance: "Compliance",
        super_admin: "Super Admin",
    }
    return map[key] || key
}

function roleKeyToColor(key: string): "blue" | "orange" | "teal" | "red" {
    const map: Record<string, "blue" | "orange" | "teal" | "red"> = {
        marketing: "blue",
        sme: "orange",
        compliance: "red",
        super_admin: "blue",
    }
    return map[key] || "blue"
}

function sortRoleKeys(keys: string[]): string[] {
    return [...keys].sort((a, b) => {
        const ai = ROLE_KEY_ORDER.indexOf(a)
        const bi = ROLE_KEY_ORDER.indexOf(b)
        return (ai === -1 ? 999 : ai) - (bi === -1 ? 999 : bi)
    })
}

function sortUsersList(list: UserRow[]): UserRow[] {
    const getSortStatus = (u: UserRow) => {
        if (u.status === "Inactive") return 2; // deactivated is last
        if (u.roles.length === 0) return 1;    // unassigned is second to last
        return 0;                             // active with roles is first
    }
    return [...list].sort((a, b) => {
        const sa = getSortStatus(a)
        const sb = getSortStatus(b)
        if (sa !== sb) return sa - sb;
        return a.name.localeCompare(b.name);
    })
}

function SelectField({
    id,
    value,
    onChange,
    options,
    placeholder = "Select",
}: {
    id: string
    value: string
    onChange: (v: string) => void
    options: { label: string; value: string }[]
    placeholder?: string
}) {
    return (
        <div className="relative w-full">
            <select
                id={id}
                value={value}
                onChange={(e) => onChange(e.target.value)}
                className="h-10 w-full appearance-none rounded-md border border-input bg-background px-3 pr-9 text-sm text-foreground shadow-sm outline-none focus-visible:ring-1 focus-visible:ring-ring focus:border-blue-500 focus:ring-blue-500"
            >
                <option value="">{placeholder}</option>
                {options.map((o) => (
                    <option key={o.value} value={o.value} className="bg-background">
                        {o.label}
                    </option>
                ))}
            </select>
            <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 flex flex-col items-center gap-[2px] text-muted-foreground">
                <svg width="8" height="5" viewBox="0 0 8 5" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
                    <path d="M1 4L4 1L7 4" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round"/>
                </svg>
                <svg width="8" height="5" viewBox="0 0 8 5" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
                    <path d="M1 1L4 4L7 1" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round"/>
                </svg>
            </span>
        </div>
    )
}

export default function SuperAdminPage() {
    const [page, setPage] = React.useState(1)
    const [headerSearch, setHeaderSearch] = React.useState("")
    const [selectedIds, setSelectedIds] = React.useState<Set<string>>(new Set())
    const [createUserOpen, setCreateUserOpen] = React.useState(false)
    const [roleModalDepartment, setRoleModalDepartment] = React.useState("")
    const [deptSuggestions, setDeptSuggestions] = React.useState<string[]>([])
    const [users, setUsers] = React.useState<UserRow[]>([])
    const [roles, setRoles] = React.useState<RoleOption[]>([])
    const [currentUserId, setCurrentUserId] = React.useState<string>("")
    const [currentUserRoles, setCurrentUserRoles] = React.useState<string[]>([])
    const [savingRoles, setSavingRoles] = React.useState(false)
    const [roleModalOpen, setRoleModalOpen] = React.useState(false)
    const [roleModalTargetUserIds, setRoleModalTargetUserIds] = React.useState<string[]>([])
    const [roleModalSelection, setRoleModalSelection] = React.useState<Set<string>>(new Set())
    const [roleModalTitle, setRoleModalTitle] = React.useState("Assign Roles")
    const [actionError, setActionError] = React.useState<string | null>(null)
    const [userToDeactivate, setUserToDeactivate] = React.useState<{id: string, name: string} | null>(null)
    const [pendingTasks, setPendingTasks] = React.useState<{id: string, type: string, document_name: string, stage: string}[] | null>(null)
    const [loadingTasks, setLoadingTasks] = React.useState(false)
    const [unassignSuperAdminUser, setUnassignSuperAdminUser] = React.useState<{id: string, name: string} | null>(null)

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

    // Filters
    const [nameFilter, setNameFilter] = React.useState("")
    const [emailFilter, setEmailFilter] = React.useState("")
    const [deptFilter, setDeptFilter] = React.useState("")
    const [statusFilter, setStatusFilter] = React.useState("")
    const [roleFilter, setRoleFilter] = React.useState("")
    const [filteredUsers, setFilteredUsers] = React.useState<UserRow[]>([])

    const departmentOptions = React.useMemo(() => {
        const depts = Array.from(new Set(users.map((u) => u.department))).filter(Boolean)
        return depts.sort().map((d) => ({ label: d, value: d }))
    }, [users])

    const statusOptions = React.useMemo(() => [
        { label: "Active", value: "Active" },
        { label: "Inactive", value: "Inactive" },
    ], [])

    const roleOptions = React.useMemo(() => [
        { label: "Marketing", value: "marketing" },
        { label: "SME Reviewer", value: "sme" },
        { label: "Compliance", value: "compliance" },
        { label: "Super Admin", value: "super_admin" },
    ], [])

    React.useEffect(() => {
        if (!roleModalOpen) return
        let cancelled = false
        void apiFetch<string[]>("/users/departments")
            .then((list) => {
                if (!cancelled) {
                    if (Array.isArray(list)) setDeptSuggestions(withMarketingDepartment(list))
                    else setDeptSuggestions(withMarketingDepartment([]))
                }
            })
            .catch(() => {
                if (!cancelled) setDeptSuggestions(withMarketingDepartment([]))
            })
        return () => {
            cancelled = true
        }
    }, [roleModalOpen, withMarketingDepartment])

    const mapServerUser = React.useCallback((u: any): UserRow => {
        const rawRoles: string[] = Array.isArray(u.roles)
            ? u.roles.filter((rk: string) => !HIDDEN_ROLE_KEYS.has(String(rk)))
            : []
        const sorted = sortRoleKeys(rawRoles)
        const primaryRoleKey = sorted[0] || ""
        const displayRole = sorted.length > 0
            ? sorted.map(roleKeyToDisplay).join(", ")
            : "Unassigned"
        const color = roleKeyToColor(primaryRoleKey)

        const assigned = u.assigned_date || (u.created_at ? String(u.created_at).slice(0, 10) : "-")
        return {
            id: String(u.id),
            name: u.name || "Unknown",
            email: u.email || "",
            department: u.department || "Unassigned",
            role: displayRole,
            roles: sorted,
            roleColor: color,
            assignedDate: assigned,
            status: (u.status || "").toLowerCase() === "inactive" ? "Inactive" : "Active",
        }
    }, [])

    const refreshUsers = React.useCallback(async () => {
        const result = await apiFetch("/users")
        if (!Array.isArray(result)) return
        const mapped = sortUsersList(result.map(mapServerUser))
        setUsers(mapped)
        setFilteredUsers(mapped)
        setPage(1)
    }, [mapServerUser])

    React.useEffect(() => {
        const bootstrap = async () => {
            try {
                const [usersRes, rolesRes, me]: [any, any, any] = await Promise.all([
                    apiFetch("/users"),
                    apiFetch("/roles"),
                    documentsApi.getUserInfo(),
                ])
                if (Array.isArray(usersRes)) {
                    const mapped = sortUsersList(usersRes.map(mapServerUser))
                    setUsers(mapped)
                    setFilteredUsers(mapped)
                    setPage(1)
                }
                if (Array.isArray(rolesRes)) {
                    setRoles(
                        rolesRes
                            .filter((r: any) => String(r.name) !== "owner")
                            .map((r: any) => ({
                                id: String(r.id),
                                name: String(r.name),
                                display_name: r.display_name ? String(r.display_name) : undefined,
                            }))
                    )
                }
                if (me?.id) {
                    setCurrentUserId(String(me.id))
                    setCurrentUserRoles(me.roles || [])
                }
            } catch (e) {
                console.error(e)
            }
        }
        bootstrap()
    }, [mapServerUser])

    const handleCreateUserChallenge = React.useCallback(async (data: NewUserData) => {
        const res = await apiFetch<{ session: string; message?: string }>("/auth/admin/create-user/challenge", {
            method: "POST",
            body: JSON.stringify({
                email: data.email,
                password: data.password || "",
                full_name: data.fullName,
                department: data.department,
                roles: data.roles,
            }),
        })
        if (!res?.session) throw new Error("No session returned from server.")
        return res.session
    }, [])

    const handleCreateUserConfirm = React.useCallback(
        async (session: string, otp: string) => {
            await apiFetch("/auth/admin/create-user/confirm", {
                method: "POST",
                body: JSON.stringify({ session, otp }),
            })
            await refreshUsers()
        },
        [refreshUsers]
    )

    const handleCreateUserResend = React.useCallback(async (session: string) => {
        await apiFetch("/auth/admin/create-user/resend", {
            method: "POST",
            body: JSON.stringify({ session }),
        })
    }, [])

    const applyFilters = () => {
        let result = users
        if (nameFilter) result = result.filter((u) => u.name.toLowerCase().includes(nameFilter.toLowerCase()))
        if (emailFilter) result = result.filter((u) => u.email.toLowerCase().includes(emailFilter.toLowerCase()))
        if (deptFilter) result = result.filter((u) => u.department.toLowerCase().includes(deptFilter.toLowerCase()))
        if (statusFilter) {
            const sf = statusFilter.toLowerCase()
            result = result.filter((u) => {
                const displayStatus = (u.status === "Inactive" || u.roles.length === 0) ? "inactive" : "active"
                return displayStatus === sf
            })
        }
        if (roleFilter) {
            const rf = roleFilter.toLowerCase()
            result = result.filter((u) =>
                u.role.toLowerCase().includes(rf) ||
                u.roles.some((r) => r.toLowerCase().includes(rf) || roleKeyToDisplay(r).toLowerCase().includes(rf))
            )
        }
        
        result = sortUsersList(result)
        
        setFilteredUsers(result)
        setPage(1)
    }

    const visibleUsers = React.useMemo(() => {
        const q = headerSearch.trim().toLowerCase()
        if (!q) return filteredUsers
        return filteredUsers.filter((u) => (u.name || "").toLowerCase().includes(q))
    }, [filteredUsers, headerSearch])

    const totalPages = Math.max(1, Math.ceil(visibleUsers.length / PAGE_SIZE))
    const paginatedUsers = visibleUsers.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE)

    React.useEffect(() => {
        setPage(1)
    }, [visibleUsers.length])

    const toggleSelect = (id: string) => {
        setSelectedIds((prev) => {
            const next = new Set(prev)
            if (next.has(id)) next.delete(id)
            else next.add(id)
            return next
        })
    }

    const toggleSelectAll = () => {
        const pageIds = paginatedUsers.filter(u => u.status !== "Inactive").map((u) => u.id)
        if (pageIds.length === 0) return
        
        setSelectedIds((prev) => {
            const next = new Set(prev)
            const allSelected = pageIds.every((id) => prev.has(id))
            if (allSelected) {
                pageIds.forEach((id) => next.delete(id))
            } else {
                pageIds.forEach((id) => next.add(id))
            }
            return next
        })
    }

    const getPageNumbers = () => {
        const pages: number[] = []
        const maxVisible = 5
        let start = Math.max(1, page - Math.floor(maxVisible / 2))
        const end = Math.min(totalPages, start + maxVisible - 1)
        start = Math.max(1, end - maxVisible + 1)
        for (let i = start; i <= end; i++) pages.push(i)
        return pages
    }

    const openRoleModalForUsers = React.useCallback(
        async (userIds: string[], title: string) => {
            if (!userIds.length) return
            setActionError(null)
            setRoleModalTitle(title)
            setRoleModalTargetUserIds(userIds)
            const firstId = userIds[0]
            const row = users.find((u) => u.id === firstId)
            const pref =
                row?.department?.trim() && row.department !== "Unassigned"
                    ? row.department.trim()
                    : ""
            setRoleModalDepartment(pref)
            setRoleModalOpen(true)
            try {
                // Prefill from first target user (works for edit + bulk)
                const first = userIds[0]
                const current: any = await apiFetch(`/user-roles/${first}`)
                const roleIds: string[] = Array.isArray(current?.roles)
                    ? current.roles.map((id: any) => String(id))
                    : []
                setRoleModalSelection(new Set(roleIds))
            } catch (e) {
                console.error(e)
                setRoleModalSelection(new Set())
            }
        },
        [users],
    )

    const saveRolesForTargets = React.useCallback(async () => {
        if (!roleModalTargetUserIds.length || !currentUserId) return
        try {
            setActionError(null)
            setSavingRoles(true)
            const selectedRoleIds = Array.from(roleModalSelection)
            for (const userId of roleModalTargetUserIds) {
                const current: any = await apiFetch(`/user-roles/${userId}`)
                const currentRoleIds: string[] = Array.isArray(current?.roles)
                    ? current.roles.map((id: any) => String(id))
                    : []

                const toAdd = selectedRoleIds.filter((id) => !currentRoleIds.includes(id))
                const toRemove = currentRoleIds.filter((id) => !selectedRoleIds.includes(id))

                for (const roleId of toAdd) {
                    await apiFetch("/user-roles", {
                        method: "POST",
                        body: JSON.stringify({
                            user_id: userId,
                            role_id: roleId,
                            assigned_by: currentUserId,
                        }),
                    })
                }
                for (const roleId of toRemove) {
                    await apiFetch("/user-roles", {
                        method: "DELETE",
                        body: JSON.stringify({
                            user_id: userId,
                            role_id: roleId,
                            assigned_by: currentUserId,
                        }),
                    })
                }
            }
            const deptTrim = roleModalDepartment.trim()
            if (deptTrim) {
                for (const userId of roleModalTargetUserIds) {
                    await apiFetch(`/users/${userId}/profile`, {
                        method: "PUT",
                        body: JSON.stringify({ department: deptTrim }),
                    })
                }
            }
            invalidateUserMeCache()
            await refreshUsers()
            setRoleModalOpen(false)
        } catch (e: any) {
            console.error(e)
            setActionError(e?.message || "Failed to update user roles. Please try again.")
        } finally {
            setSavingRoles(false)
        }
    }, [currentUserId, refreshUsers, roleModalDepartment, roleModalSelection, roleModalTargetUserIds])

    const unassignUser = React.useCallback(async (userId: string) => {
        if (!currentUserId) return
        try {
            setActionError(null)
            const current: any = await apiFetch(`/user-roles/${userId}`)
            const currentRoleIds: string[] = Array.isArray(current?.roles)
                ? current.roles.map((id: any) => String(id))
                : []
            for (const roleId of currentRoleIds) {
                await apiFetch("/user-roles", {
                    method: "DELETE",
                    body: JSON.stringify({
                        user_id: userId,
                        role_id: roleId,
                        assigned_by: currentUserId,
                    }),
                })
            }
            await refreshUsers()
        } catch (e: any) {
            console.error(e)
            setActionError(e?.message || "Failed to unassign roles. Please try again.")
        }
    }, [currentUserId, refreshUsers])

    return (
        <MainLayout
            header={{
                breadcrumbs: [
                    { label: "ComplyCore", to: "/dashboard/default" },
                    { label: "Users" },
                ],
                searchQuery: headerSearch,
                onSearchChange: setHeaderSearch,
                searchPlaceholder: "Search users",
            }}
        >
            <div className="w-full space-y-6">
                {/* Title */}
                <div>
                    <h1 className="text-lg font-bold text-foreground">Users</h1>
                    <p className="mt-0.5 text-sm text-muted-foreground">
                        Immutable record of all compliance review activities and version history.
                    </p>
                </div>

                {actionError && !roleModalOpen && (
                    <div className="rounded-lg border border-destructive/40 bg-destructive/5 px-4 py-3 text-sm text-destructive">
                        {actionError}
                    </div>
                )}

                {/* Filters */}
                <div className="flex flex-wrap items-end gap-4 rounded-xl border border-border bg-card px-5 py-4 shadow-sm dark:shadow-[-4px_4px_12px_rgba(0,0,0,0.3)]">
                    <div className="min-w-[130px] flex-1">
                        <label className="mb-1 block text-xs font-medium text-muted-foreground">Name</label>
                        <div className="relative">
                            <input
                                type="text"
                                placeholder="Search"
                                className="w-full rounded-md border border-input bg-background py-2 pl-8 pr-3 text-sm text-foreground placeholder:text-muted-foreground focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                                value={nameFilter}
                                onChange={(e) => setNameFilter(e.target.value)}
                            />
                        </div>
                    </div>
                    <div className="min-w-[130px] flex-1">
                        <label className="mb-1 block text-xs font-medium text-muted-foreground">Email</label>
                        <div className="relative">
                            <input
                                type="text"
                                placeholder="Search"
                                className="w-full rounded-md border border-input bg-background py-2 pl-8 pr-3 text-sm text-foreground placeholder:text-muted-foreground focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                                value={emailFilter}
                                onChange={(e) => setEmailFilter(e.target.value)}
                            />
                        </div>
                    </div>
                    <div className="min-w-[130px] flex-1">
                        <label className="mb-1 block text-xs font-medium text-muted-foreground">Department</label>
                        <SelectField
                            id="department"
                            value={deptFilter}
                            onChange={setDeptFilter}
                            options={departmentOptions}
                            placeholder="Select Dept"
                        />
                    </div>
                    <div className="min-w-[130px] flex-1">
                        <label className="mb-1 block text-xs font-medium text-muted-foreground">Status</label>
                        <SelectField
                            id="status"
                            value={statusFilter}
                            onChange={setStatusFilter}
                            options={statusOptions}
                            placeholder="Select Status"
                        />
                    </div>
                    <div className="min-w-[130px] flex-1">
                        <label className="mb-1 block text-xs font-medium text-muted-foreground">Role</label>
                        <SelectField
                            id="role"
                            value={roleFilter}
                            onChange={setRoleFilter}
                            options={roleOptions}
                            placeholder="Select Role"
                        />
                    </div>
                    <button
                        type="button"
                        className="rounded-lg bg-gradient-to-r from-[#128ADA] to-[#662CC4] px-6 py-2 text-sm font-medium text-white shadow-sm transition-all hover:from-[#1078B8] hover:to-[#5526A3]"
                        onClick={applyFilters}
                    >
                        Apply
                    </button>
                </div>

                {/* List of Users section */}
                <div className="w-full rounded-xl border border-border bg-card shadow-sm dark:shadow-[-4px_4px_12px_rgba(0,0,0,0.3)]">
                    {/* Header */}
                    <div className="flex items-center justify-between px-6 py-4">
                        <div>
                            <h2 className="text-sm font-bold text-foreground">List of Users</h2>
                            <p className="mt-0.5 text-xs text-muted-foreground">
                                Select and assign roles to users.
                            </p>
                        </div>
                        <div className="flex items-center gap-3">
                            <button
                                type="button"
                                className="rounded-lg bg-gradient-to-r from-[#128ADA] to-[#662CC4] px-4 py-2 text-sm font-medium text-white shadow-sm transition-all hover:from-[#1078B8] hover:to-[#5526A3]"
                                onClick={() => setCreateUserOpen(true)}
                            >
                                Create New User
                            </button>
                            <button
                                type="button"
                                className="flex items-center gap-1.5 rounded-lg border border-input bg-card px-4 py-2 text-xs font-medium text-foreground shadow-sm transition-all hover:bg-accent hover:text-accent-foreground"
                                onClick={() =>
                                    openRoleModalForUsers(Array.from(selectedIds), "Bulk Assign Roles")
                                }
                            >
                                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><line x1="22" y1="11" x2="16" y2="11"/></svg>
                                Bulk Assign ({selectedIds.size})
                            </button>
                        </div>
                    </div>

                    {/* Table */}
                    <div className="overflow-x-auto">
                        <table className="w-full text-left text-sm">
                            <thead>
                                <tr className="border-y border-border bg-muted/30">
                                    <th className="w-10 px-4 py-3">
                                        <input
                                            type="checkbox"
                                            className="h-4 w-4 rounded border-gray-300 accent-blue-600 dark:border-border disabled:opacity-50"
                                            checked={
                                                paginatedUsers.filter(u => u.status !== "Inactive").length > 0 &&
                                                paginatedUsers.filter(u => u.status !== "Inactive").every((u) => selectedIds.has(u.id))
                                            }
                                            onChange={toggleSelectAll}
                                            disabled={paginatedUsers.filter(u => u.status !== "Inactive").length === 0}
                                        />
                                    </th>
                                    <th className="whitespace-nowrap px-4 py-3 text-xs font-medium text-muted-foreground">Name</th>
                                    <th className="whitespace-nowrap px-4 py-3 text-xs font-medium text-muted-foreground">Email</th>
                                    <th className="whitespace-nowrap px-4 py-3 text-xs font-medium text-muted-foreground">Department</th>
                                    <th className="whitespace-nowrap px-4 py-3 text-xs font-medium text-muted-foreground">Role</th>
                                    <th className="whitespace-nowrap px-4 py-3 text-xs font-medium text-muted-foreground">Assigned Date</th>
                                    <th className="whitespace-nowrap px-4 py-3 text-xs font-medium text-muted-foreground">Status</th>
                                    <th className="whitespace-nowrap px-4 py-3 text-xs font-medium text-muted-foreground min-w-[220px]">Action</th>
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-border">
                                {paginatedUsers.map((user, idx) => {
                                    const showHeader = user.status === "Inactive" && (idx === 0 || paginatedUsers[idx - 1].status === "Active");
                                    
                                    return (
                                    <React.Fragment key={user.id}>
                                        {showHeader && (
                                            <tr className="bg-muted/10">
                                                <td colSpan={8} className="px-4 py-3 text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                                                    Deactivated Users
                                                </td>
                                            </tr>
                                        )}
                                        <tr className={`hover:bg-muted/50 ${user.status === "Inactive" ? "opacity-60 grayscale-[50%]" : ""}`}>
                                        <td className="px-4 py-3">
                                            <input
                                                type="checkbox"
                                                className="h-4 w-4 rounded border-gray-300 accent-blue-600 dark:border-border disabled:opacity-50 disabled:cursor-not-allowed"
                                                checked={selectedIds.has(user.id)}
                                                onChange={() => toggleSelect(user.id)}
                                                disabled={user.status === "Inactive"}
                                            />
                                        </td>
                                        <td className="whitespace-nowrap px-4 py-3 font-medium text-foreground">
                                            {user.name}
                                        </td>
                                        <td className="whitespace-nowrap px-4 py-3 text-muted-foreground">
                                            {user.email}
                                        </td>
                                        <td className="whitespace-nowrap px-4 py-3 text-muted-foreground">
                                            {user.department}
                                        </td>
                                        <td className="px-4 py-3">
                                            <div className="flex flex-wrap gap-1">
                                                {user.roles.length > 0 ? user.roles.map((rk) => (
                                                    <span key={rk} className={`inline-block rounded-md border px-2.5 py-1 text-xs font-medium ${roleBadgeStyles[roleKeyToColor(rk)]}`}>
                                                        {roleKeyToDisplay(rk)}
                                                    </span>
                                                )) : (
                                                    <span className={`inline-block rounded-md border px-2.5 py-1 text-xs font-medium ${roleBadgeStyles.blue}`}>
                                                        Unassigned
                                                    </span>
                                                )}
                                            </div>
                                        </td>
                                        <td className="whitespace-nowrap px-4 py-3 text-muted-foreground">
                                            {user.assignedDate}
                                        </td>
                                        <td className="whitespace-nowrap px-4 py-3">
                                            {user.status === "Inactive" || user.roles.length === 0 ? (
                                                <span className="inline-flex items-center gap-1.5 rounded-md border border-gray-200 bg-gray-50 px-2.5 py-1 text-xs font-medium text-gray-500 dark:border-gray-800 dark:bg-gray-900 dark:text-gray-400">
                                                    Inactive
                                                </span>
                                            ) : (
                                                <span className="flex items-center gap-1.5 text-sm">
                                                    <span className="h-2 w-2 rounded-full bg-emerald-500" />
                                                    <span className="font-medium text-emerald-600 dark:text-emerald-400">{user.status}</span>
                                                </span>
                                            )}
                                        </td>
                                        <td className="whitespace-nowrap px-4 py-3 min-w-[220px]">
                                            <div className="flex items-center gap-2 text-foreground">
                                                {user.status === "Inactive" ? (
                                                    <button
                                                        type="button"
                                                        className="flex items-center gap-1 whitespace-nowrap text-emerald-600 hover:text-emerald-700 dark:text-emerald-400 dark:hover:text-emerald-300"
                                                        title="Reactivate"
                                                        onClick={async () => {
                                                            try {
                                                                await apiFetch(`/users/${user.id}/reactivate`, { method: "POST" })
                                                                await refreshUsers()
                                                            } catch(e) {
                                                                console.error(e)
                                                                setActionError("Failed to reactivate user.")
                                                            }
                                                        }}
                                                    >
                                                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/></svg>
                                                        <span className="text-xs">Reactivate</span>
                                                    </button>
                                                ) : (
                                                    <>
                                                        <button
                                                            type="button"
                                                            className="flex items-center gap-1 whitespace-nowrap text-muted-foreground hover:text-foreground dark:text-foreground/80"
                                                            title="Edit"
                                                            onClick={() => openRoleModalForUsers([user.id], "Edit User Roles")}
                                                        >
                                                            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" className="dark:invert dark:opacity-90">
                                                                <rect width="24" height="24" rx="8" fill="#E3F5FF" />
                                                                <path d="M16 11.4999L12.5 7.99994L14.1437 6.3562C14.1902 6.30896 14.2457 6.27142 14.3069 6.24585C14.368 6.22021 14.4337 6.20703 14.5 6.20703C14.5663 6.20703 14.632 6.22021 14.6931 6.24585C14.7543 6.27142 14.8098 6.30896 14.8563 6.3562L17.6437 9.14368C17.691 9.19025 17.7285 9.24567 17.7541 9.30682C17.7797 9.36798 17.7929 9.43365 17.7929 9.49994C17.7929 9.56622 17.7797 9.6319 17.7541 9.69305C17.7285 9.75421 17.691 9.80969 17.6437 9.8562L16 11.4999Z" fill="#1C1C1C" />
                                                                <path d="M14.5 5.70703C14.5 5.70703 14.7006 5.70682 14.8857 5.78418C14.8857 5.78418 15.0719 5.86177 15.2129 6.00488L17.9971 8.79004C17.9971 8.79004 18.1372 8.92825 18.2148 9.11328C18.2148 9.11328 18.293 9.2991 18.293 9.5C18.293 9.50378 18.2916 9.70225 18.2148 9.88574C18.2148 9.88574 18.1382 10.0699 17.9971 10.21L10.3535 17.8535C10.2598 17.9473 10.1326 18 10 18H7C6.99816 18 6.58521 17.9992 6.29297 17.707C6.29297 17.707 6.00003 17.4142 6 17V14.2061C6 14.2001 6.00031 14.0073 6.07422 13.8271C6.07422 13.8271 6.14966 13.6442 6.28906 13.5039L13.79 6.00293C13.79 6.00293 13.9289 5.86177 14.1143 5.78418C14.1255 5.77955 14.3055 5.70703 14.5 5.70703ZM7 14.207V17H9.79297L17.293 9.5L14.5 6.70703L7 14.207Z" fill="#1C1C1C" />
                                                            </svg>
                                                            <span className="text-xs">Edit</span>
                                                        </button>
                                                        {user.roles.length > 0 && (
                                                            <>
                                                                <button
                                                                    type="button"
                                                                    className="flex items-center gap-1 whitespace-nowrap text-muted-foreground hover:text-foreground dark:text-foreground/80"
                                                                    title="Unassign"
                                                                    onClick={() => {
                                                                        if (user.roles.includes("super_admin")) {
                                                                            setUnassignSuperAdminUser({ id: user.id, name: user.name });
                                                                        } else {
                                                                            unassignUser(user.id);
                                                                        }
                                                                    }}
                                                                >
                                                                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><line x1="22" y1="11" x2="16" y2="11"/></svg>
                                                                    <span className="text-xs">Unassign</span>
                                                                </button>
                                                                {(!user.roles.includes("super_admin") || currentUserRoles.includes("owner")) && (
                                                                    <button
                                                                        type="button"
                                                                        className="flex items-center gap-1 whitespace-nowrap text-muted-foreground hover:text-red-500 dark:text-foreground/80 dark:hover:text-red-400"
                                                                        title="Deactivate"
                                                                        onClick={async () => {
                                                                            setUserToDeactivate({ id: user.id, name: user.name })
                                                                            setLoadingTasks(true)
                                                                            setPendingTasks(null)
                                                                            try {
                                                                                const res: any = await apiFetch(`/users/${user.id}/pending-tasks`)
                                                                                setPendingTasks(res.tasks || [])
                                                                            } catch(e) {
                                                                                console.error(e)
                                                                                setPendingTasks([])
                                                                            } finally {
                                                                                setLoadingTasks(false)
                                                                            }
                                                                        }}
                                                                    >
                                                                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><line x1="10" y1="11" x2="10" y2="17"/><line x1="14" y1="11" x2="14" y2="17"/></svg>
                                                                        <span className="text-xs">Deactivate</span>
                                                                    </button>
                                                                )}
                                                            </>
                                                        )}
                                                    </>
                                                )}
                                            </div>
                                        </td>
                                    </tr>
                                    </React.Fragment>
                                )})}
                            </tbody>
                        </table>
                    </div>

                    {/* Pagination */}
                    <div className="flex items-center justify-end gap-1 border-t border-border px-6 py-4">
                        <button
                            type="button"
                            className="grid h-8 w-8 place-items-center rounded-md text-sm text-muted-foreground hover:bg-muted disabled:opacity-40"
                            disabled={page === 1}
                            onClick={() => setPage((p) => p - 1)}
                        >
                            ←
                        </button>
                        {getPageNumbers().map((p) => (
                            <button
                                key={p}
                                type="button"
                                className={`grid h-8 w-8 place-items-center rounded-md text-sm font-medium ${p === page
                                    ? "bg-gradient-to-r from-[#128ADA] to-[#662CC4] text-white shadow-sm"
                                    : "text-muted-foreground hover:bg-muted"
                                    }`}
                                onClick={() => setPage(p)}
                            >
                                {p}
                            </button>
                        ))}
                        <button
                            type="button"
                            className="grid h-8 w-8 place-items-center rounded-md text-sm text-muted-foreground hover:bg-muted disabled:opacity-40"
                            disabled={page === totalPages}
                            onClick={() => setPage((p) => p + 1)}
                        >
                            →
                        </button>
                    </div>
                </div>
            </div>

            {createUserOpen && (
                <CreateUserModal
                    onClose={() => setCreateUserOpen(false)}
                    onChallenge={handleCreateUserChallenge}
                    onConfirm={handleCreateUserConfirm}
                    onResend={handleCreateUserResend}
                />
            )}

            {roleModalOpen && (
                <div className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/30 px-4">
                    <div className="w-full max-w-lg rounded-xl border border-border bg-card p-5 shadow-xl">
                        <div className="mb-4 flex items-center justify-between">
                            <div>
                                <h3 className="text-base font-semibold text-foreground">{roleModalTitle}</h3>
                                <p className="text-xs text-muted-foreground">
                                    Assign roles and department. Users need both before they can use the app.
                                </p>
                            </div>
                            <button
                                type="button"
                                className="rounded-md p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
                                onClick={() => setRoleModalOpen(false)}
                                aria-label="Close"
                            >
                                <X className="h-4 w-4" />
                            </button>
                        </div>

                        {actionError && (
                            <div className="mb-4 rounded-lg border border-destructive/40 bg-destructive/5 px-4 py-3 text-sm text-destructive">
                                {actionError}
                            </div>
                        )}

                        <div className="max-h-72 space-y-2 overflow-auto rounded-lg border border-border p-3">
                            {roles.map((r) => {
                                const checked = roleModalSelection.has(r.id)
                                const isSuperAdminRole = r.name === "super_admin"
                                const isEditingSuperAdmin = roleModalTargetUserIds.some(id => users.find(u => u.id === id)?.roles.includes("super_admin"))
                                const isTargetSuperAdminLocked = isEditingSuperAdmin && isSuperAdminRole
                                const hasSuperAdmin = Array.from(roleModalSelection).some(id => roles.find(rl => rl.id === id)?.name === "super_admin")
                                const isDisabled = isTargetSuperAdminLocked || (!checked && (
                                    roleModalSelection.size >= 2 ||
                                    (roleModalSelection.size === 1 && !hasSuperAdmin && !isSuperAdminRole)
                                ))

                                return (
                                    <label
                                        key={r.id}
                                        className={`flex cursor-pointer items-center gap-3 rounded-md px-2 py-1.5 hover:bg-muted/60 ${isDisabled ? 'opacity-50 cursor-not-allowed' : ''}`}
                                    >
                                        <input
                                            type="checkbox"
                                            className="h-4 w-4 rounded border-gray-300 accent-blue-600 disabled:cursor-not-allowed"
                                            checked={isTargetSuperAdminLocked ? true : checked}
                                            disabled={isDisabled}
                                            onChange={() =>
                                                setRoleModalSelection((prev) => {
                                                    const next = new Set(prev)
                                                    if (next.has(r.id)) {
                                                        if (!isTargetSuperAdminLocked) {
                                                            next.delete(r.id)
                                                        }
                                                    } else {
                                                        next.add(r.id)
                                                    }
                                                    return next
                                                })
                                            }
                                        />
                                        <div className="text-sm text-foreground">
                                            {r.display_name || r.name}
                                        </div>
                                    </label>
                                )
                            })}
                        </div>

                        <div className="mt-4 space-y-1.5">
                            <Label htmlFor="role-modal-dept" className="text-xs font-medium">
                                Department
                            </Label>
                            <select
                                id="role-modal-dept"
                                className="h-9 w-full rounded-md border border-input bg-background px-3 text-sm text-foreground"
                                value={roleModalDepartment}
                                onChange={(e) => setRoleModalDepartment(e.target.value)}
                            >
                                <option value="">Select department</option>
                                {deptSuggestions.map((d) => (
                                    <option key={d} value={d}>
                                        {d}
                                    </option>
                                ))}
                            </select>
                            <p className="text-[11px] text-muted-foreground">
                                Saved to all selected users. Department options are loaded from existing DB records.
                            </p>
                        </div>

                        <div className="mt-4 flex justify-end gap-2">
                            <button
                                type="button"
                                className="rounded-md border border-input px-4 py-2 text-sm text-foreground hover:bg-muted"
                                onClick={() => setRoleModalOpen(false)}
                                disabled={savingRoles}
                            >
                                Cancel
                            </button>
                            <button
                                type="button"
                                className="rounded-md bg-gradient-to-r from-[#128ADA] to-[#662CC4] px-4 py-2 text-sm font-medium text-white shadow-sm transition-all hover:from-[#1078B8] hover:to-[#5526A3] disabled:opacity-60"
                                onClick={saveRolesForTargets}
                                disabled={savingRoles}
                            >
                                {savingRoles ? "Saving..." : "Save roles & department"}
                            </button>
                        </div>
                    </div>
                </div>
            )}

            {userToDeactivate && (
                <div className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/20 backdrop-blur-sm px-4">
                    <div className="w-full max-w-md rounded-xl border border-border bg-card p-6 shadow-xl dark:bg-[#1e293b]">
                        <div className="flex items-start justify-between">
                            <h3 className="text-lg font-semibold text-foreground">Deactivate User</h3>
                            <button
                                type="button"
                                onClick={() => { setUserToDeactivate(null); setPendingTasks(null); }}
                                className="rounded-md p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
                            >
                                <X className="h-4 w-4" />
                            </button>
                        </div>
                        
                        <div className="mt-4">
                            {loadingTasks ? (
                                <p className="text-sm text-muted-foreground">Checking for pending tasks...</p>
                            ) : (
                                <>
                                    {pendingTasks && pendingTasks.length > 0 ? (
                                        <>
                                            <p className="text-sm font-medium text-red-600 dark:text-red-400 mb-2">
                                                Cannot deactivate {userToDeactivate.name}. They have {pendingTasks.length} pending task(s):
                                            </p>
                                            <ul className="list-disc pl-5 text-sm text-muted-foreground max-h-40 overflow-y-auto mb-4">
                                                {pendingTasks.map((t) => (
                                                    <li key={t.id}>{t.document_name} ({t.stage.replace('_', ' ')})</li>
                                                ))}
                                            </ul>
                                            <p className="text-sm text-muted-foreground">Please reassign or complete these tasks first.</p>
                                        </>
                                    ) : (
                                        <p className="text-sm text-muted-foreground leading-relaxed">
                                            Are you sure you want to deactivate {userToDeactivate.name}?
                                        </p>
                                    )}
                                </>
                            )}
                        </div>

                        <div className="mt-6 flex justify-end gap-3">
                            <button
                                type="button"
                                className="rounded-lg border border-input px-4 py-2 text-sm font-medium text-foreground hover:bg-muted"
                                onClick={() => { setUserToDeactivate(null); setPendingTasks(null); }}
                            >
                                Cancel
                            </button>
                            <button
                                type="button"
                                disabled={loadingTasks || (pendingTasks && pendingTasks.length > 0)}
                                className="rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-red-700 disabled:opacity-50"
                                onClick={async () => {
                                    try {
                                        await apiFetch(`/users/${userToDeactivate.id}`, { method: "DELETE" })
                                        setUserToDeactivate(null)
                                        setPendingTasks(null)
                                        await refreshUsers()
                                    } catch(e) {
                                        console.error(e)
                                        setActionError("Failed to deactivate user.")
                                        setUserToDeactivate(null)
                                        setPendingTasks(null)
                                    }
                                }}
                            >
                                Deactivate
                            </button>
                        </div>
                    </div>
                </div>
            )}

            {unassignSuperAdminUser && (
                <ConfirmationModal
                    isOpen={true}
                    title="Action Restricted"
                    message="To unassign a Super Admin, please contact support@complycore.ca for this action."
                    confirmText="OK"
                    cancelText="Close"
                    onConfirm={() => setUnassignSuperAdminUser(null)}
                    onCancel={() => setUnassignSuperAdminUser(null)}
                    isDanger={false}
                />
            )}
        </MainLayout>
    )
}