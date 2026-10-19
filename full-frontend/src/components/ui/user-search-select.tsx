import * as React from "react"
import { Search } from "lucide-react"
import { usersApi } from "@/lib/api"
import { cn } from "@/lib/utils"

interface UserSearchSelectProps {
  role?: string
  value: string
  onChange: (value: string) => void
  disabled?: boolean
  placeholder?: string
  defaultLabel?: string
  className?: string
}

export function UserSearchSelect({
  role,
  value,
  onChange,
  disabled,
  placeholder = "Search reviewers...",
  defaultLabel = "All reviewers can claim",
  className,
}: UserSearchSelectProps) {
  const [open, setOpen] = React.useState(false)
  const [query, setQuery] = React.useState("")
  const [users, setUsers] = React.useState<any[]>([])
  const [loading, setLoading] = React.useState(false)
  const containerRef = React.useRef<HTMLDivElement>(null)

  // Fetch users on mount or when query/role changes
  React.useEffect(() => {
    if (!open) return
    
    const fetchUsers = async () => {
      setLoading(true)
      try {
        const data = await usersApi.list(role, query)
        setUsers(data)
      } catch (error) {
        console.error("Failed to fetch users:", error)
      } finally {
        setLoading(false)
      }
    }

    const timer = setTimeout(fetchUsers, 300)
    return () => clearTimeout(timer)
  }, [role, query, open])

  // Handle outside click to close dropdown
  React.useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener("mousedown", handleClickOutside)
    return () => document.removeEventListener("mousedown", handleClickOutside)
  }, [])

  const selectedUser = users.find(u => String(u.id) === value)
  const displayLabel = selectedUser 
    ? (selectedUser.name || selectedUser.email) 
    : (value === "" ? defaultLabel : "Select user")

  return (
    <div className={cn("relative w-full", className)} ref={containerRef}>
      <button
        type="button"
        disabled={disabled}
        onClick={() => setOpen(!open)}
        className={cn(
          "flex h-10 w-full items-center justify-between rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring disabled:cursor-not-allowed disabled:opacity-50",
          disabled && "opacity-60"
        )}
      >
        <span className="truncate">{displayLabel}</span>
        <svg
          width="15"
          height="15"
          viewBox="0 0 15 15"
          fill="none"
          xmlns="http://www.w3.org/2000/svg"
          className="h-4 w-4 opacity-50"
        >
          <path
            d="M3.13523 6.15803C3.3241 5.95657 3.64052 5.94637 3.84197 6.13523L7.5 9.56464L11.158 6.13523C11.3595 5.94637 11.6759 5.95657 11.8648 6.15803C12.0536 6.35949 12.0434 6.67591 11.842 6.86477L7.84197 10.6148C7.64491 10.7995 7.35509 10.7995 7.15803 10.6148L3.15803 6.86477C2.95657 6.67591 2.94637 6.35949 3.13523 6.15803Z"
            fill="currentColor"
            fillRule="evenodd"
            clipRule="evenodd"
          ></path>
        </svg>
      </button>

      {open && (
        <div className="absolute z-50 mt-1 w-full rounded-md border border-border bg-card p-1 shadow-md animate-in fade-in-0 zoom-in-95">
          <div className="flex items-center border-b border-foreground/10 px-3 pb-2 pt-1 font-sans">
            <Search className="mr-2 h-4 w-4 shrink-0 opacity-50" />
            <input
              className="flex h-8 w-full rounded-md bg-transparent py-3 text-sm outline-none placeholder:text-muted-foreground disabled:cursor-not-allowed disabled:opacity-50"
              placeholder={placeholder}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              autoFocus
            />
          </div>
          <div className="max-h-[220px] overflow-y-auto p-1 scrollbar-thin scrollbar-thumb-foreground/10">
            <button
              type="button"
              className={cn(
                "relative flex w-full cursor-pointer select-none items-center rounded-sm px-2 py-2 text-sm outline-none hover:bg-accent hover:text-accent-foreground",
                value === "" && "bg-accent/50"
              )}
              onClick={() => {
                onChange("")
                setOpen(false)
              }}
            >
              {defaultLabel}
            </button>
            {loading ? (
              <div className="py-4 text-center text-xs text-muted-foreground italic">Searching...</div>
            ) : users.length === 0 ? (
              <div className="py-4 text-center text-xs text-muted-foreground italic">No users found for "{query}"</div>
            ) : (
              users.map((user) => (
                <button
                  key={user.id}
                  type="button"
                  className={cn(
                    "relative flex w-full cursor-pointer select-none items-center rounded-md px-2 py-2 text-sm outline-none hover:bg-accent hover:text-accent-foreground transition-all duration-150",
                    String(user.id) === value && "bg-[#128BDA]/10 text-[#128BDA] font-medium"
                  )}
                  onClick={() => {
                    onChange(String(user.id))
                    setOpen(false)
                  }}
                >
                  <div className="flex flex-col items-start gap-0.5">
                    <span className="text-sm">{user.name || "Unknown User"}</span>
                    <span className="text-[10.5px] opacity-60 font-normal">{user.email}</span>
                  </div>
                </button>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  )
}
