import * as React from "react"
import { MainLayout } from "@/components/layout/MainLayout"
import { Pencil, Trash2 } from "lucide-react"

type UserRole = {
    id: number
    name: string
    avatar: string
    role: string
    active: boolean
}

const initialUsers: UserRole[] = [
    { id: 1, name: "Kate Morrison", avatar: "KM", role: "Marketing User", active: true },
    { id: 2, name: "Kate Morrison", avatar: "KM", role: "SME (Subject Matter Expert)", active: true },
    { id: 3, name: "Kate Morrison", avatar: "KM", role: "Compliance", active: false },
    { id: 4, name: "Kate Morrison", avatar: "KM", role: "Marketing User", active: true },
    { id: 5, name: "Kate Morrison", avatar: "KM", role: "Super Admin", active: true },
    { id: 6, name: "Kate Morrison", avatar: "KM", role: "SME (Subject Matter Expert)", active: true },
    { id: 7, name: "Kate Morrison", avatar: "KM", role: "Compliance", active: false },
    { id: 8, name: "Kate Morrison", avatar: "KM", role: "Marketing User", active: true },
]

const roleOptions = [
    "Marketing User",
    "SME (Subject Matter Expert)",
    "Compliance",
    "Super Admin",
    "Admin",
]

function Toggle({ checked, onChange }: { checked: boolean; onChange: () => void }) {
    return (
        <button
            type="button"
            onClick={onChange}
            className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ${checked ? "bg-emerald-500" : "bg-gray-200"
                }`}
            aria-label="Toggle active"
        >
            <span
                className={`pointer-events-none inline-block h-5 w-5 rounded-full bg-white shadow-sm transition-transform duration-200 ${checked ? "translate-x-5" : "translate-x-0"
                    }`}
            />
        </button>
    )
}

export default function AssignRolePage() {
    const [headerSearch, setHeaderSearch] = React.useState("")
    const [users, setUsers] = React.useState(initialUsers)
    const [editingId, setEditingId] = React.useState<number | null>(1)
    const [editRole, setEditRole] = React.useState("Admin")
    const [selectedIds, setSelectedIds] = React.useState<Set<number>>(new Set())

    const filteredUsers = React.useMemo(() => {
        const q = headerSearch.trim().toLowerCase()
        if (!q) return users
        return users.filter((u) => u.name.toLowerCase().includes(q))
    }, [headerSearch, users])

    const toggleActive = (id: number) => {
        setUsers((prev) =>
            prev.map((u) => (u.id === id ? { ...u, active: !u.active } : u))
        )
    }

    const toggleSelect = (id: number) => {
        setSelectedIds((prev) => {
            const next = new Set(prev)
            if (next.has(id)) next.delete(id)
            else next.add(id)
            return next
        })
    }




    const handleSave = (id: number) => {
        setUsers((prev) =>
            prev.map((u) => (u.id === id ? { ...u, role: editRole } : u))
        )
        setEditingId(null)
    }

    return (
        <MainLayout
            header={{
                breadcrumbs: [
                    { label: "ComplyCore", to: "/dashboard/default" },
                    { label: "Assign Role" },
                ],
                searchQuery: headerSearch,
                onSearchChange: setHeaderSearch,
                searchPlaceholder: "Search users",
            }}
        >
            <div className="w-full space-y-6">
                {/* Title */}
                <div>
                    <h1 className="text-lg font-bold text-foreground">Assign Role</h1>
                    <p className="mt-0.5 text-sm text-muted-foreground">
                        Update your personal information and email address.
                    </p>
                </div>

                {/* Table */}
                <div className="w-full overflow-hidden rounded-xl bg-white shadow-sm">
                    <div className="overflow-x-auto">
                        <table className="w-full text-left text-sm">
                            <thead>
                                <tr className="border-b bg-white">
                                    <th className="w-10 px-4 py-3">
                                    </th>
                                    <th className="px-4 py-3 text-xs font-medium text-muted-foreground">
                                        User
                                    </th>
                                    <th className="px-4 py-3 text-xs font-medium text-muted-foreground">
                                        Role
                                    </th>
                                    <th className="px-4 py-3 text-xs font-medium text-muted-foreground">
                                        Permissions
                                    </th>
                                    <th className="px-4 py-3 text-xs font-medium text-muted-foreground">
                                        Action
                                    </th>
                                </tr>
                            </thead>
                            <tbody className="divide-y">
                                {filteredUsers.map((user) => (
                                    <React.Fragment key={user.id}>
                                        <tr className="hover:bg-[#FAFAFB]">
                                            <td className="px-4 py-3">
                                                <input
                                                    type="checkbox"
                                                    className="h-4 w-4 rounded border-gray-300 accent-blue-600"
                                                    checked={selectedIds.has(user.id)}
                                                    onChange={() => toggleSelect(user.id)}
                                                />
                                            </td>
                                            <td className="px-4 py-3">
                                                <div className="flex items-center gap-3">
                                                    <div className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-gray-100">
                                                        <img
                                                            src="/shared/default-avatar.png"
                                                            alt={user.name}
                                                            className="h-8 w-8 rounded-full object-cover"
                                                        />
                                                    </div>
                                                    <span className="whitespace-nowrap font-medium text-foreground">
                                                        {user.name}
                                                    </span>
                                                </div>
                                            </td>
                                            <td className="px-4 py-3">
                                                <div className="relative inline-block">
                                                    <select
                                                        className="appearance-none rounded-md border bg-white py-2 pl-3 pr-8 text-sm text-foreground focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                                                        value={user.role}
                                                        onChange={(e) =>
                                                            setUsers((prev) =>
                                                                prev.map((u) =>
                                                                    u.id === user.id
                                                                        ? { ...u, role: e.target.value }
                                                                        : u
                                                                )
                                                            )
                                                        }
                                                    >
                                                        {roleOptions.map((r) => (
                                                            <option key={r} value={r}>
                                                                {r}
                                                            </option>
                                                        ))}
                                                    </select>
                                                    <svg
                                                        className="pointer-events-none absolute right-2 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
                                                        fill="none"
                                                        stroke="currentColor"
                                                        viewBox="0 0 24 24"
                                                    >
                                                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                                                    </svg>
                                                </div>
                                            </td>
                                            <td className="px-4 py-3">
                                                <div className="flex items-center gap-3">
                                                    <button
                                                        type="button"
                                                        className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
                                                        onClick={() => {
                                                            setEditingId(editingId === user.id ? null : user.id)
                                                            setEditRole(user.role)
                                                        }}
                                                    >
                                                        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                                                            <rect width="24" height="24" rx="8" fill="#E3F5FF" />
                                                            <path d="M16 11.4999L12.5 7.99994L14.1437 6.3562C14.1902 6.30896 14.2457 6.27142 14.3069 6.24585C14.368 6.22021 14.4337 6.20703 14.5 6.20703C14.5663 6.20703 14.632 6.22021 14.6931 6.24585C14.7543 6.27142 14.8098 6.30896 14.8563 6.3562L17.6437 9.14368C17.691 9.19025 17.7285 9.24567 17.7541 9.30682C17.7797 9.36798 17.7929 9.43365 17.7929 9.49994C17.7929 9.56622 17.7797 9.6319 17.7541 9.69305C17.7285 9.75421 17.691 9.80969 17.6437 9.8562L16 11.4999Z" fill="#1C1C1C" />
                                                            <path d="M14.5 5.70703C14.5 5.70703 14.7006 5.70682 14.8857 5.78418C14.8857 5.78418 15.0719 5.86177 15.2129 6.00488L17.9971 8.79004C17.9971 8.79004 18.1372 8.92825 18.2148 9.11328C18.2148 9.11328 18.293 9.2991 18.293 9.5C18.293 9.50378 18.2916 9.70225 18.2148 9.88574C18.2148 9.88574 18.1382 10.0699 17.9971 10.21L10.3535 17.8535C10.2598 17.9473 10.1326 18 10 18H7C6.99816 18 6.58521 17.9992 6.29297 17.707C6.29297 17.707 6.00003 17.4142 6 17V14.2061C6 14.2001 6.00031 14.0073 6.07422 13.8271C6.07422 13.8271 6.14966 13.6442 6.28906 13.5039L13.79 6.00293C13.79 6.00293 13.9289 5.86177 14.1143 5.78418C14.1255 5.77955 14.3055 5.70703 14.5 5.70703ZM7 14.207V17H9.79297L17.293 9.5L14.5 6.70703L7 14.207Z" fill="#1C1C1C" />
                                                            <path d="M15.6462 11.8533L15.6464 11.8536C15.7402 11.9473 15.8674 12 16 12C16.1326 12 16.2598 11.9473 16.3536 11.8536C16.4473 11.7598 16.5 11.6326 16.5 11.5C16.5 11.3674 16.4473 11.2402 16.3536 11.1464L16.3533 11.1462L12.8536 7.64651C12.7598 7.55268 12.6326 7.5 12.5 7.5C12.3674 7.5 12.2402 7.55268 12.1464 7.64645C12.0527 7.74021 12 7.86739 12 8C12 8.13261 12.0527 8.25979 12.1464 8.35355L15.6462 11.8533Z" fill="#1C1C1C" />
                                                            <path d="M17.5 17H10C9.72386 17 9.5 17.2239 9.5 17.5C9.5 17.7761 9.72386 18 10 18H17.5C17.7761 18 18 17.7761 18 17.5C18 17.2239 17.7761 17 17.5 17Z" fill="#1C1C1C" />
                                                        </svg>
                                                        <span className="text-xs">Edit</span>
                                                    </button>
                                                    <button
                                                        type="button"
                                                        className="flex items-center gap-1 text-sm text-muted-foreground hover:text-red-500"
                                                    >
                                                        <Trash2 className="h-3.5 w-3.5" />
                                                        <span className="text-xs">Delete</span>
                                                    </button>
                                                </div>
                                            </td>
                                            <td className="px-4 py-3">
                                                <Toggle
                                                    checked={user.active}
                                                    onChange={() => toggleActive(user.id)}
                                                />
                                            </td>
                                        </tr>

                                        {/* Edit row */}
                                        {editingId === user.id && (
                                            <tr className="bg-[#F7F8F9]">
                                                <td colSpan={5} className="px-4 py-3">
                                                    <div className="flex items-center gap-3 pl-10">
                                                        <select
                                                            className="appearance-none rounded-md border bg-white py-2 pl-3 pr-8 text-sm text-foreground focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                                                            value={editRole}
                                                            onChange={(e) => setEditRole(e.target.value)}
                                                        >
                                                            {roleOptions.map((r) => (
                                                                <option key={r} value={r}>
                                                                    {r}
                                                                </option>
                                                            ))}
                                                        </select>
                                                        <button
                                                            type="button"
                                                            className="rounded-md bg-emerald-500 px-4 py-2 text-xs font-medium text-white hover:bg-emerald-600"
                                                            onClick={() => handleSave(user.id)}
                                                        >
                                                            Save
                                                        </button>
                                                    </div>
                                                </td>
                                            </tr>
                                        )}
                                    </React.Fragment>
                                ))}
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>
        </MainLayout>
    )
}