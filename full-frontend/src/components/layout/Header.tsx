import * as React from "react"
import { NavLink, useLocation, useNavigate } from "react-router-dom"
import { ChevronDown, Moon, Search, Sun, Menu, X, HelpCircle } from "lucide-react"

import { AiComplianceMark } from "@/components/brand/AiComplianceMark"
import { MENU_ITEMS, resolveTenantNavPath } from "@/components/layout/Sidebar"
import { useTheme } from "@/context/theme-context"
import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { notificationsApi, type NotificationItem, documentsApi, authApi } from "@/lib/api"
import { ReportIssueModal } from "@/components/models/ReportIssueModal"

export type Breadcrumb = {
  label: string
  to?: string
}

export type HeaderProps = {
  breadcrumbs?: Breadcrumb[]
  className?: string
  onUploadClick?: () => void
  sidebarCollapsed?: boolean
  mobileSidebarOpen?: boolean
  onToggleSidebar?: () => void
  searchQuery?: string
  onSearchChange?: (val: string) => void
  searchPlaceholder?: string
}

export function Header({
  className,
  onUploadClick,
  breadcrumbs: _breadcrumbs,
  sidebarCollapsed: _sidebarCollapsed,
  mobileSidebarOpen: _mobileSidebarOpen,
  onToggleSidebar: _onToggleSidebar,
  searchQuery,
  onSearchChange,
  searchPlaceholder = "Search Document",
}: HeaderProps) {
  const { theme, toggleTheme } = useTheme()
  const navigate = useNavigate()
  const location = useLocation()
  const isUploadPage = location.pathname === "/upload-document"
  const [notifications, setNotifications] = React.useState<NotificationItem[]>([])
  const [userRoles, setUserRoles] = React.useState<string[]>([])
  const [orgSlug, setOrgSlug] = React.useState<string | null>(null)
  const [currentUser, setCurrentUser] = React.useState<{ name: string; initial: string }>({
    name: "Loading...",
    initial: "?",
  })
  const [isProfileMenuOpen, setIsProfileMenuOpen] = React.useState(false)
  const [isHelpOpen, setIsHelpOpen] = React.useState(false)
  const [rawUserInfo, setRawUserInfo] = React.useState<any>(null)
  const [isDocumentsMenuOpen, setIsDocumentsMenuOpen] = React.useState(false)
  // const [isSocialMediaMenuOpen, setIsSocialMediaMenuOpen] = React.useState(false) // Commented out: Social Media
  const [isUsersMenuOpen, setIsUsersMenuOpen] = React.useState(false)
  const [notifOpen, setNotifOpen] = React.useState(false)
  const [notifLoading, setNotifLoading] = React.useState(false)
  const [isMobileMenuOpen, setIsMobileMenuOpen] = React.useState(false)
  const [isSearchExpanded, setIsSearchExpanded] = React.useState(false)
  const profileMenuRef = React.useRef<HTMLDivElement | null>(null)
  const documentsMenuRef = React.useRef<HTMLDivElement | null>(null)
  // const socialMediaMenuRef = React.useRef<HTMLDivElement | null>(null) // Commented out: Social Media
  const usersMenuRef = React.useRef<HTMLDivElement | null>(null)
  const notifBoxRef = React.useRef<HTMLDivElement | null>(null)
  const mobileMenuRef = React.useRef<HTMLDivElement | null>(null)

  const unreadCount = React.useMemo(
    () => notifications.filter((n) => !n.is_read).length,
    [notifications]
  )

  const loadNotifications = React.useCallback(async () => {
    try {
      setNotifLoading(true)
      const items = await notificationsApi.list()
      setNotifications(items || [])
    } catch {
      // keep header resilient
    } finally {
      setNotifLoading(false)
    }
  }, [])

  React.useEffect(() => {
    let cancelled = false
    let eventSource: EventSource | null = null
    let reconnectTimer: number | undefined
    let reconnectDelay = 2000
    let fallbackPollTimer: number | undefined

    const stopFallbackPolling = () => {
      if (fallbackPollTimer) {
        window.clearInterval(fallbackPollTimer)
        fallbackPollTimer = undefined
      }
    }

    const startFallbackPolling = () => {
      stopFallbackPolling()
      fallbackPollTimer = window.setInterval(() => {
        void loadNotifications()
      }, 60000)
    }

    const connectNotificationsStream = () => {
      if (cancelled) return

      try {
        eventSource = new EventSource(notificationsApi.streamUrl(), { withCredentials: true })
        eventSource.onopen = () => {
          stopFallbackPolling()
          reconnectDelay = 2000
        }
        eventSource.onmessage = () => {
          void loadNotifications()
        }
        eventSource.onerror = () => {
          eventSource?.close()
          eventSource = null
          if (cancelled) return
          startFallbackPolling()
          reconnectDelay = Math.min(reconnectDelay * 2, 30000)
          reconnectTimer = window.setTimeout(connectNotificationsStream, reconnectDelay)
        }
      } catch {
        startFallbackPolling()
      }
    }

    void loadNotifications()
    connectNotificationsStream()

    // Fetch user info for role-based permissions and tenant routes
    documentsApi
      .getUserInfo()
      .then((info: any) => {
        setRawUserInfo(info)
        const name = info?.full_name || info?.email || "User"
        setCurrentUser({ name, initial: name.charAt(0).toUpperCase() })
        if (Array.isArray(info?.roles)) setUserRoles(info.roles.map((r: unknown) => String(r)))
        const slug = info?.organization?.slug
        setOrgSlug(typeof slug === "string" && slug.trim() ? slug.trim() : null)
      })
      .catch(() => {})

    return () => {
      cancelled = true
      eventSource?.close()
      stopFallbackPolling()
      if (reconnectTimer) window.clearTimeout(reconnectTimer)
    }
  }, [loadNotifications])

  const isMarketingOrAdmin = userRoles.includes("marketing")

  React.useEffect(() => {
    if (!notifOpen) return
    const onMouseDown = (e: MouseEvent) => {
      if (!notifBoxRef.current) return
      if (!notifBoxRef.current.contains(e.target as Node)) {
        setNotifOpen(false)
      }
    }
    document.addEventListener("mousedown", onMouseDown)
    return () => document.removeEventListener("mousedown", onMouseDown)
  }, [notifOpen])

  React.useEffect(() => {
    const onMouseDown = (e: MouseEvent) => {
      if (!mobileMenuRef.current) return
      if (!mobileMenuRef.current.contains(e.target as Node)) {
        setIsMobileMenuOpen(false)
      }
    }
    document.addEventListener("mousedown", onMouseDown)
    return () => document.removeEventListener("mousedown", onMouseDown)
  }, [])

  React.useEffect(() => {
    const onMouseDown = (e: MouseEvent) => {
      if (!profileMenuRef.current) return
      if (!profileMenuRef.current.contains(e.target as Node)) {
        setIsProfileMenuOpen(false)
      }
    }
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") setIsProfileMenuOpen(false)
    }
    document.addEventListener("mousedown", onMouseDown)
    document.addEventListener("keydown", onKeyDown)
    return () => {
      document.removeEventListener("mousedown", onMouseDown)
      document.removeEventListener("keydown", onKeyDown)
    }
  }, [])

  React.useEffect(() => {
    const onMouseDown = (e: MouseEvent) => {
      if (!documentsMenuRef.current) return
      if (!documentsMenuRef.current.contains(e.target as Node)) {
        setIsDocumentsMenuOpen(false)
      }
    }
    document.addEventListener("mousedown", onMouseDown)
    return () => document.removeEventListener("mousedown", onMouseDown)
  }, [])

  /* Commented out: Social Media menu close-on-outside-click
  React.useEffect(() => {
    const onMouseDown = (e: MouseEvent) => {
      if (!socialMediaMenuRef.current) return
      if (!socialMediaMenuRef.current.contains(e.target as Node)) {
        setIsSocialMediaMenuOpen(false)
      }
    }
    document.addEventListener("mousedown", onMouseDown)
    return () => document.removeEventListener("mousedown", onMouseDown)
  }, [])
  */

  React.useEffect(() => {
    const onMouseDown = (e: MouseEvent) => {
      if (!usersMenuRef.current) return
      if (!usersMenuRef.current.contains(e.target as Node)) {
        setIsUsersMenuOpen(false)
      }
    }
    document.addEventListener("mousedown", onMouseDown)
    return () => document.removeEventListener("mousedown", onMouseDown)
  }, [])

  const openNotificationRef = React.useCallback((n: NotificationItem) => {
    // mark read best-effort; navigation still works even if this fails
    notificationsApi.markRead(n.id).catch(() => {})

    // Optimistically update local state so the badge count drops immediately
    setNotifications((prev) =>
      prev.map((item) => (item.id === n.id ? { ...item, is_read: true } : item))
    )

    if (orgSlug && n.reference_id) {
      if (n.reference_type === "document" || n.reference_type === "content_comment" || n.reference_type === "finding") {
        navigate(`/orgs/${encodeURIComponent(orgSlug)}/validate-documents/detail/${n.reference_id}`)
      }
    }
  }, [navigate, orgSlug, setNotifications])

  const visibleMenuItems = React.useMemo(() => {
    return MENU_ITEMS.filter((link) => {
      if (!link.roles || link.roles.length === 0) return true
      return link.roles.some((r) => userRoles.includes(r))
    }).map((link) => ({ ...link, to: resolveTenantNavPath(orgSlug, link.to) }))
  }, [orgSlug, userRoles])

  const dashboardItem = React.useMemo(
    () => visibleMenuItems.find((item) => item.label === "Dashboard"),
    [visibleMenuItems]
  )
  const reviewItem = React.useMemo(
    () => visibleMenuItems.find((item) => item.label === "Documents"),
    [visibleMenuItems]
  )
  const allDocumentsItem = React.useMemo(
    () => visibleMenuItems.find((item) => item.label === "Published Documents"),
    [visibleMenuItems]
  )
  const auditTrailItem = React.useMemo(
    () => visibleMenuItems.find((item) => item.label === "Audit Trail"),
    [visibleMenuItems]
  )
  const createAssignUserItem = React.useMemo(
    () => visibleMenuItems.find((item) => item.label === "Users"),
    [visibleMenuItems]
  )
  const userProfilesItem = React.useMemo(
    () => visibleMenuItems.find((item) => item.label === "User Profiles"),
    [visibleMenuItems]
  )
  /* Commented out Social Media items
  const socialMediaAccountsItem = React.useMemo(
    () => visibleMenuItems.find((item) => item.label === "Social Media"),
    [visibleMenuItems]
  )
  const socialMediaSettingsItem = React.useMemo(
    () => visibleMenuItems.find((item) => item.label === "Social Media Settings"),
    [visibleMenuItems]
  )
  */
  const ownerOperationsItem = React.useMemo(
    () => visibleMenuItems.find((item) => item.label === "Owner Operations"),
    [visibleMenuItems]
  )
  const organizationsItem = React.useMemo(
    () => visibleMenuItems.find((item) => item.label === "Organizations"),
    [visibleMenuItems]
  )

  type NavDropdownEntry = { to: string; label: string }

  const documentsDropdownItems = React.useMemo<NavDropdownEntry[]>(() => {
    const items: NavDropdownEntry[] = []
    if (reviewItem) items.push({ to: reviewItem.to, label: "All Documents" })
    if (allDocumentsItem) items.push({ to: allDocumentsItem.to, label: "Publish Documents" })
    return items
  }, [reviewItem, allDocumentsItem])

  /* Commented out Social Media dropdown items list
  const socialMediaDropdownItems = React.useMemo<NavDropdownEntry[]>(() => {
    const items: NavDropdownEntry[] = []
    if (socialMediaAccountsItem)
      items.push({ to: socialMediaAccountsItem.to, label: "Social Media Accounts" })
    if (socialMediaSettingsItem)
      items.push({ to: socialMediaSettingsItem.to, label: "Social Media Settings" })
    return items
  }, [socialMediaAccountsItem, socialMediaSettingsItem])
  */

  const usersDropdownItems = React.useMemo<NavDropdownEntry[]>(() => {
    const items: NavDropdownEntry[] = []
    if (createAssignUserItem)
      items.push({ to: createAssignUserItem.to, label: "Users" })
    return items
  }, [createAssignUserItem])

  const isDocumentsSectionActive = React.useMemo(() => {
    const current = `${location.pathname}${location.search}`
    return documentsDropdownItems.some((it) => it.to && current.startsWith(it.to))
  }, [documentsDropdownItems, location.pathname, location.search])

  /* Commented out Social Media active section check
  const isSocialMediaSectionActive = React.useMemo(() => {
    const current = `${location.pathname}${location.search}`
    return socialMediaDropdownItems.some((it) => it.to && current.startsWith(it.to))
  }, [socialMediaDropdownItems, location.pathname, location.search])
  */

  const isUsersSectionActive = React.useMemo(() => {
    const current = `${location.pathname}${location.search}`
    return usersDropdownItems.some((it) => it.to && current.startsWith(it.to))
  }, [usersDropdownItems, location.pathname, location.search])

  const directLinkClassName = ({ isActive }: { isActive: boolean }) =>
    cn(
      "whitespace-nowrap flex items-center justify-center rounded-lg px-2 xl:px-3 py-2 text-[13px] transition-colors",
      isActive
        ? "bg-[#174199] text-white"
        : "text-muted-foreground hover:bg-accent hover:text-foreground"
    )

  const handleOpenProfile = () => {
    setIsProfileMenuOpen(false)
    navigate("/user-profile")
  }

  const handleLogout = async () => {
    setIsProfileMenuOpen(false)
    await authApi.logout().catch(() => undefined)
    navigate("/login")
  }

  return (
    <header
      className={cn(
        "sticky top-0 z-50 border-b bg-background",
        className
      )}
    >
      {isSearchExpanded && onSearchChange && (
        <div className="absolute inset-0 z-[60] flex items-center bg-background px-4 md:hidden">
          <Search className="absolute left-7 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            className="h-10 w-full rounded-md border bg-muted pl-9 pr-10 text-sm placeholder:text-muted-foreground focus-visible:ring-1"
            placeholder={searchPlaceholder}
            value={searchQuery || ""}
            onChange={(e) => onSearchChange?.(e.target.value)}
            autoFocus
          />
          <button
            className="absolute right-6 top-1/2 -translate-y-1/2 p-1 text-muted-foreground hover:text-foreground"
            onClick={() => setIsSearchExpanded(false)}
            aria-label="Close search"
          >
            <X className="h-5 w-5" />
          </button>
        </div>
      )}
      <div className="flex min-h-16 items-center justify-between gap-4 px-4 sm:px-6">
        <div className="flex min-w-0 flex-1 items-center gap-4 lg:gap-6">
          <div className="lg:hidden relative" ref={mobileMenuRef}>
            <Button variant="ghost" size="icon" onClick={() => setIsMobileMenuOpen(!isMobileMenuOpen)} aria-label="Menu">
              <Menu className="h-5 w-5" />
            </Button>
            {isMobileMenuOpen && (
              <div className="absolute left-0 top-11 z-50 w-[240px] rounded-lg border bg-card p-2 shadow-lg max-h-[80vh] overflow-y-auto flex flex-col gap-1">
                {visibleMenuItems.map(it => (
                  <NavLink key={it.to} to={it.to} end className="flex items-center gap-2 rounded-md px-3 py-2 text-sm text-foreground hover:bg-accent" onClick={() => setIsMobileMenuOpen(false)}>
                    <span className="flex items-center justify-center w-5 h-5 [&>svg]:w-5 [&>svg]:h-5 text-muted-foreground">{it.icon}</span>
                    {it.label}
                  </NavLink>
                ))}
              </div>
            )}
          </div>
          <AiComplianceMark className="hidden sm:block" />
          <nav className="hidden min-w-0 flex-1 items-center gap-1 overflow-visible lg:flex">
            {dashboardItem ? (
              <NavLink to={dashboardItem.to} end className={directLinkClassName} title={dashboardItem.label}>
                <span className="hidden xl:inline">{dashboardItem.label}</span>
                <span className="xl:hidden flex items-center justify-center w-5 h-5 [&>svg]:w-5 [&>svg]:h-5">{dashboardItem.icon}</span>
              </NavLink>
            ) : null}

            {documentsDropdownItems.length === 1 ? (
              <NavLink to={documentsDropdownItems[0].to} end className={directLinkClassName} title={documentsDropdownItems[0].label}>
                <span className="hidden xl:inline">{documentsDropdownItems[0].label}</span>
                <span className="xl:hidden flex items-center justify-center w-5 h-5 [&>svg]:w-5 [&>svg]:h-5">{reviewItem?.icon || allDocumentsItem?.icon}</span>
              </NavLink>
            ) : documentsDropdownItems.length >= 2 ? (
              <div className="relative z-50" ref={documentsMenuRef}>
                <button
                  type="button"
                  onClick={() => setIsDocumentsMenuOpen((prev) => !prev)}
                  className={cn(
                    "flex items-center justify-center gap-1 whitespace-nowrap rounded-lg px-2 xl:px-3 py-2 text-[13px] transition-colors",
                    isDocumentsSectionActive
                      ? "bg-[#174199] text-white"
                      : "text-muted-foreground hover:bg-accent hover:text-foreground"
                  )}
                  title="Documents"
                >
                  <span className="hidden xl:inline">Documents</span>
                  <span className="xl:hidden flex items-center justify-center w-5 h-5 [&>svg]:w-5 [&>svg]:h-5">{reviewItem?.icon || allDocumentsItem?.icon}</span>
                  <ChevronDown className={cn("h-4 w-4 transition-transform hidden xl:block", isDocumentsMenuOpen ? "rotate-180" : "")} />
                </button>
                {isDocumentsMenuOpen ? (
                  <div className="absolute left-0 top-11 z-50 w-[200px] rounded-lg border bg-card p-1 shadow-lg">
                    {documentsDropdownItems.map((it) => (
                      <button
                        key={it.to}
                        type="button"
                        onClick={() => {
                          setIsDocumentsMenuOpen(false)
                          navigate(it.to)
                        }}
                        className="flex h-9 w-full items-center rounded-md px-3 text-left text-sm text-foreground hover:bg-accent"
                      >
                        {it.label}
                      </button>
                    ))}
                  </div>
                ) : null}
              </div>
            ) : null}

            {auditTrailItem ? (
              <NavLink to={auditTrailItem.to} end className={directLinkClassName} title={auditTrailItem.label}>
                <span className="hidden xl:inline">{auditTrailItem.label}</span>
                <span className="xl:hidden flex items-center justify-center w-5 h-5 [&>svg]:w-5 [&>svg]:h-5">{auditTrailItem.icon}</span>
              </NavLink>
            ) : null}

            {usersDropdownItems.length === 1 ? (
              <NavLink to={usersDropdownItems[0].to} end className={directLinkClassName} title={usersDropdownItems[0].label}>
                <span className="hidden xl:inline">{usersDropdownItems[0].label}</span>
                <span className="xl:hidden flex items-center justify-center w-5 h-5 [&>svg]:w-5 [&>svg]:h-5">{createAssignUserItem?.icon || userProfilesItem?.icon}</span>
              </NavLink>
            ) : usersDropdownItems.length >= 2 ? (
              <div className="relative z-50" ref={usersMenuRef}>
                <button
                  type="button"
                  onClick={() => setIsUsersMenuOpen((prev) => !prev)}
                  className={cn(
                    "flex items-center justify-center gap-1 whitespace-nowrap rounded-lg px-2 xl:px-3 py-2 text-[13px] transition-colors",
                    isUsersSectionActive
                      ? "bg-[#174199] text-white"
                      : "text-muted-foreground hover:bg-accent hover:text-foreground"
                  )}
                  title="Users"
                >
                  <span className="hidden xl:inline">Users</span>
                  <span className="xl:hidden flex items-center justify-center w-5 h-5 [&>svg]:w-5 [&>svg]:h-5">{createAssignUserItem?.icon || userProfilesItem?.icon}</span>
                  <ChevronDown className={cn("h-4 w-4 transition-transform hidden xl:block", isUsersMenuOpen ? "rotate-180" : "")} />
                </button>
                {isUsersMenuOpen ? (
                  <div className="absolute left-0 top-11 z-50 w-[220px] rounded-lg border bg-card p-1 shadow-lg">
                    {usersDropdownItems.map((it) => (
                      <button
                        key={it.to}
                        type="button"
                        onClick={() => {
                          setIsUsersMenuOpen(false)
                          navigate(it.to)
                        }}
                        className="flex h-9 w-full items-center rounded-md px-3 text-left text-sm text-foreground hover:bg-accent"
                      >
                        {it.label}
                      </button>
                    ))}
                  </div>
                ) : null}
              </div>
            ) : null}

            {/* Commented out Social Media section
            socialMediaDropdownItems.length === 1 ? (
              <NavLink to={socialMediaDropdownItems[0].to} end className={directLinkClassName} title={socialMediaDropdownItems[0].label}>
                <span className="hidden xl:inline">{socialMediaDropdownItems[0].label}</span>
                <span className="xl:hidden flex items-center justify-center w-5 h-5 [&>svg]:w-5 [&>svg]:h-5">{socialMediaAccountsItem?.icon || socialMediaSettingsItem?.icon}</span>
              </NavLink>
            ) : socialMediaDropdownItems.length >= 2 ? (
              <div className="relative z-50" ref={socialMediaMenuRef}>
                <button
                  type="button"
                  onClick={() => setIsSocialMediaMenuOpen((prev) => !prev)}
                  className={cn(
                    "flex items-center justify-center gap-1 whitespace-nowrap rounded-lg px-2 xl:px-3 py-2 text-[13px] transition-colors",
                    isSocialMediaSectionActive
                      ? "bg-[#174199] text-white"
                      : "text-muted-foreground hover:bg-accent hover:text-foreground"
                  )}
                  title="Social Media"
                >
                  <span className="hidden xl:inline">Social Media</span>
                  <span className="xl:hidden flex items-center justify-center w-5 h-5 [&>svg]:w-5 [&>svg]:h-5">{socialMediaAccountsItem?.icon || socialMediaSettingsItem?.icon}</span>
                  <ChevronDown className={cn("h-4 w-4 transition-transform hidden xl:block", isSocialMediaMenuOpen ? "rotate-180" : "")} />
                </button>
                {isSocialMediaMenuOpen ? (
                  <div className="absolute left-0 top-11 z-50 w-[220px] rounded-lg border bg-card p-1 shadow-lg">
                    {socialMediaDropdownItems.map((it) => (
                      <button
                        key={it.to}
                        type="button"
                        onClick={() => {
                          setIsSocialMediaMenuOpen(false)
                          navigate(it.to)
                        }}
                        className="flex h-9 w-full items-center rounded-md px-3 text-left text-sm text-foreground hover:bg-accent"
                      >
                        {it.label}
                      </button>
                    ))}
                  </div>
                ) : null}
              </div>
            ) : null
            */}

            {ownerOperationsItem ? (
              <NavLink to={ownerOperationsItem.to} end className={directLinkClassName} title={ownerOperationsItem.label}>
                <span className="hidden xl:inline">{ownerOperationsItem.label}</span>
                <span className="xl:hidden flex items-center justify-center w-5 h-5 [&>svg]:w-5 [&>svg]:h-5">{ownerOperationsItem.icon}</span>
              </NavLink>
            ) : null}

            {organizationsItem ? (
              <NavLink to={organizationsItem.to} end className={directLinkClassName} title={organizationsItem.label}>
                <span className="hidden xl:inline">{organizationsItem.label}</span>
                <span className="xl:hidden flex items-center justify-center w-5 h-5 [&>svg]:w-5 [&>svg]:h-5">{organizationsItem.icon}</span>
              </NavLink>
            ) : null}
          </nav>
        </div>

        {onSearchChange ? (
        <>
          <div className="hidden w-[160px] max-w-[20vw] md:block xl:w-[200px]">
            <div className="relative">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
              <Input
                className="h-9 border-0 bg-muted pl-8 pr-8 text-sm placeholder:text-muted-foreground focus-visible:ring-0"
                placeholder={searchPlaceholder}
                value={searchQuery || ""}
                onChange={(e) => onSearchChange?.(e.target.value)}
              />
              <button
                type="button"
                className="absolute right-1.5 top-1/2 grid h-7 w-7 -translate-y-1/2 place-items-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground"
                aria-label="Search options"
              >
                <svg width="17" height="18" viewBox="0 0 17 18" fill="none" xmlns="http://www.w3.org/2000/svg" className="h-4 w-4">
                  <path d="M3.2983 13.196C2.96023 13.196 2.65057 13.1136 2.36932 12.9489C2.08807 12.7812 1.86364 12.5568 1.69602 12.2756C1.53125 11.9943 1.44886 11.6847 1.44886 11.3466C1.44886 11.0057 1.53125 10.6946 1.69602 10.4134C1.86364 10.1321 2.08807 9.90767 2.36932 9.74006C2.65057 9.57244 2.96023 9.48864 3.2983 9.48864H4.28693V7.77557H3.2983C2.96023 7.77557 2.65057 7.69318 2.36932 7.52841C2.08807 7.3608 1.86364 7.13778 1.69602 6.85938C1.53125 6.57812 1.44886 6.26705 1.44886 5.92614C1.44886 5.58523 1.53125 5.27557 1.69602 4.99716C1.86364 4.71591 2.08807 4.4929 2.36932 4.32812C2.65057 4.16051 2.96023 4.0767 3.2983 4.0767C3.6392 4.0767 3.95028 4.16051 4.23153 4.32812C4.51278 4.4929 4.73722 4.71591 4.90483 4.99716C5.07244 5.27557 5.15625 5.58523 5.15625 5.92614V6.90625H6.86932V5.92614C6.86932 5.58523 6.9517 5.27557 7.11648 4.99716C7.28409 4.71591 7.5071 4.4929 7.78551 4.32812C8.06676 4.16051 8.37784 4.0767 8.71875 4.0767C9.05966 4.0767 9.36932 4.16051 9.64773 4.32812C9.92898 4.4929 10.152 4.71591 10.3168 4.99716C10.4844 5.27557 10.5682 5.58523 10.5682 5.92614C10.5682 6.26705 10.4844 6.57812 10.3168 6.85938C10.152 7.13778 9.92898 7.3608 9.64773 7.52841C9.36932 7.69318 9.05966 7.77557 8.71875 7.77557H7.73864V9.48864H8.71875C9.05966 9.48864 9.36932 9.57244 9.64773 9.74006C9.92898 9.90767 10.152 10.1321 10.3168 10.4134C10.4844 10.6946 10.5682 11.0057 10.5682 11.3466C10.5682 11.6847 10.4844 11.9943 10.3168 12.2756C10.152 12.5568 9.92898 12.7812 9.64773 12.9489C9.36932 13.1136 9.05966 13.196 8.71875 13.196C8.37784 13.196 8.06676 13.1136 7.78551 12.9489C7.5071 12.7812 7.28409 12.5568 7.11648 12.2756C6.9517 11.9943 6.86932 11.6847 6.86932 11.3466V10.358H5.15625V11.3466C5.15625 11.6847 5.07244 11.9943 4.90483 12.2756C4.73722 12.5568 4.51278 12.7812 4.23153 12.9489C3.95028 13.1136 3.6392 13.196 3.2983 13.196ZM3.2983 12.3267C3.48011 12.3267 3.64489 12.2827 3.79261 12.1946C3.94318 12.1065 4.0625 11.9886 4.15057 11.8409C4.24148 11.6903 4.28693 11.5256 4.28693 11.3466V10.358H3.2983C3.11932 10.358 2.95455 10.4034 2.80398 10.4943C2.65625 10.5824 2.53835 10.7017 2.45028 10.8523C2.36222 11 2.31818 11.1648 2.31818 11.3466C2.31818 11.5256 2.36222 11.6903 2.45028 11.8409C2.53835 11.9886 2.65625 12.1065 2.80398 12.1946C2.95455 12.2827 3.11932 12.3267 3.2983 12.3267ZM3.2983 6.90625H4.28693V5.92614C4.28693 5.74432 4.24148 5.57955 4.15057 5.43182C4.0625 5.28409 3.94318 5.16619 3.79261 5.07812C3.64489 4.99006 3.48011 4.94602 3.2983 4.94602C3.11932 4.94602 2.95455 4.99006 2.80398 5.07812C2.65625 5.16619 2.53835 5.28409 2.45028 5.43182C2.36222 5.57955 2.31818 5.74432 2.31818 5.92614C2.31818 6.10795 2.36222 6.27415 2.45028 6.42472C2.53835 6.57244 2.65625 6.69034 2.80398 6.77841C2.95455 6.86364 3.11932 6.90625 3.2983 6.90625ZM7.73864 6.90625H8.71875C8.90057 6.90625 9.06534 6.86364 9.21307 6.77841C9.3608 6.69034 9.47869 6.57244 9.56676 6.42472C9.65483 6.27415 9.69886 6.10795 9.69886 5.92614C9.69886 5.74432 9.65483 5.57955 9.56676 5.43182C9.47869 5.28409 9.3608 5.16619 9.21307 5.07812C9.06534 4.99006 8.90057 4.94602 8.71875 4.94602C8.53693 4.94602 8.37074 4.99006 8.22017 5.07812C8.07244 5.16619 7.95455 5.28409 7.86648 5.43182C7.78125 5.57955 7.73864 5.74432 7.73864 5.92614V6.90625ZM8.71875 12.3267C8.90057 12.3267 9.06534 12.2827 9.21307 12.1946C9.3608 12.1065 9.47869 11.9886 9.56676 11.8409C9.65483 11.6903 9.69886 11.5256 9.69886 11.3466C9.69886 11.1648 9.65483 11 9.56676 10.8523C9.47869 10.7017 9.3608 10.5824 9.21307 10.4943C9.06534 10.4034 8.90057 10.358 8.71875 10.358H7.73864V11.3466C7.73864 11.5256 7.78125 11.6903 7.86648 11.8409C7.95455 11.9886 8.07244 12.1065 8.22017 12.1946C8.37074 12.2827 8.53693 12.3267 8.71875 12.3267ZM5.15625 9.48864H6.86932V7.77557H5.15625V9.48864ZM16.0174 3.86364L13.2049 14.3125H12.2844L15.0969 3.86364H16.0174Z" fill="currentColor" fillOpacity="0.4"/>
                </svg>
              </button>
            </div>
          </div>
          <Button
            variant="ghost"
            size="icon"
            className="md:hidden text-muted-foreground/60 hover:text-foreground"
            onClick={() => setIsSearchExpanded(true)}
            aria-label="Open search"
          >
            <Search className="h-4 w-4" />
          </Button>
        </>
        ) : null}

        <div className="flex items-center gap-2">
          {isMarketingOrAdmin && (
            <Button
              disabled={isUploadPage}
              className={cn(
                "rounded-lg gap-1 px-2 sm:px-4 py-2",
                isUploadPage
                  ? "bg-muted text-muted-foreground opacity-50 cursor-not-allowed"
                  : "bg-gradient-to-r from-[#128ADA] to-[#662CC4] text-white hover:from-[#1078B8] hover:to-[#5526A3]"
              )}
              onClick={onUploadClick}
              title="Upload Document"
            >
              <svg width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg" className="h-4 w-4">
                <path d="M12.8538 8.64625C12.9002 8.6927 12.9371 8.74786 12.9622 8.80855C12.9873 8.86925 13.0003 8.9343 13.0003 9C13.0003 9.0657 12.9873 9.13075 12.9622 9.19145C12.9371 9.25214 12.9002 9.3073 12.8538 9.35375C12.8073 9.40021 12.7521 9.43706 12.6914 9.4622C12.6308 9.48734 12.5657 9.50028 12.5 9.50028C12.4343 9.50028 12.3692 9.48734 12.3086 9.4622C12.2479 9.43706 12.1927 9.40021 12.1462 9.35375L8.5 5.70687V14C8.5 14.1326 8.44732 14.2598 8.35355 14.3536C8.25979 14.4473 8.13261 14.5 8 14.5C7.86739 14.5 7.74021 14.4473 7.64645 14.3536C7.55268 14.2598 7.5 14.1326 7.5 14V5.70687L3.85375 9.35375C3.80729 9.40021 3.75214 9.43706 3.69145 9.4622C3.63075 9.48734 3.5657 9.50028 3.5 9.50028C3.4343 9.50028 3.36925 9.48734 3.30855 9.4622C3.24786 9.43706 3.19271 9.40021 3.14625 9.35375C3.09979 9.3073 3.06294 9.25214 3.0378 9.19145C3.01266 9.13075 2.99972 9.0657 2.99972 9C2.99972 8.9343 3.01266 8.86925 3.0378 8.80855C3.06294 8.74786 3.09979 8.6927 3.14625 8.64625L7.64625 4.14625C7.69269 4.09976 7.74783 4.06288 7.80853 4.03772C7.86923 4.01256 7.93429 3.99961 8 3.99961C8.06571 3.99961 8.13077 4.01256 8.19147 4.03772C8.25217 4.06288 8.30731 4.09976 8.35375 4.14625L12.8538 8.64625ZM13.5 2H2.5C2.36739 2 2.24021 2.05268 2.14645 2.14645C2.05268 2.24021 2 2.36739 2 2.5C2 2.63261 2.05268 2.75979 2.14645 2.85355C2.24021 2.94732 2.36739 3 2.5 3H13.5C13.6326 3 13.7598 2.94732 13.8536 2.85355C13.9473 2.75979 14 2.63261 14 2.5C14 2.36739 13.9473 2.24021 13.8536 2.14645C13.7598 2.05268 13.6326 2 13.5 2Z" fill="currentColor"/>
              </svg>
              <span className="hidden sm:inline ml-1">Upload Document</span>
            </Button>
          )}
          <Button
            variant="ghost"
            size="icon"
            aria-label="Report an Issue / Help"
            className="text-muted-foreground/60 hover:text-foreground gap-1 px-2.5 w-auto"
            onClick={() => setIsHelpOpen(true)}
          >
            <HelpCircle className="h-4 w-4" />
            <span className="hidden sm:inline text-xs font-medium">Help</span>
          </Button>
          <Button
            variant="ghost"
            size="icon"
            aria-label={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
            className="text-muted-foreground/60 hover:text-foreground"
            onClick={toggleTheme}
          >
            {theme === "dark" ? (
              <Sun className="h-4 w-4" />
            ) : (
              <Moon className="h-4 w-4" />
            )}
          </Button>
          <div className="relative" ref={notifBoxRef}>
            <Button
              variant="ghost"
              size="icon"
              aria-label="Notifications"
              className="relative text-muted-foreground/60 hover:text-foreground"
              onClick={() => setNotifOpen((v) => !v)}
            >
              <svg width="20" height="20" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg" className="h-4 w-4">
              <path d="M4.39038 8.12498C4.38931 7.38406 4.53488 6.65018 4.8187 5.96575C5.10251 5.28128 5.51892 4.65975 6.04382 4.13691C6.56888 3.61407 7.1922 3.20025 7.87778 2.9193C8.56351 2.63838 9.29791 2.49586 10.0389 2.49998C13.1326 2.52345 15.6091 5.09375 15.6091 8.19529V8.74998C15.6091 11.5469 16.195 13.1719 16.7106 14.0625C16.7654 14.1574 16.7944 14.2649 16.7944 14.3745C16.7946 14.484 16.7659 14.5916 16.7112 14.6865C16.6566 14.7815 16.578 14.8604 16.4834 14.9155C16.3887 14.9705 16.2811 14.9996 16.1717 15H3.82794C3.71838 14.9996 3.61081 14.9705 3.5162 14.9155C3.42145 14.8604 3.34286 14.7815 3.28824 14.6865C3.23361 14.5916 3.20493 14.484 3.20508 14.3745C3.20523 14.2649 3.23407 14.1574 3.28885 14.0625C3.80444 13.1719 4.39038 11.5469 4.39038 8.74998V8.12498Z" fill="currentColor" fillOpacity="0.4"/>
              <path fillRule="evenodd" clipRule="evenodd" d="M10.042 1.87498C10.042 1.87498 11.3109 1.88492 12.4658 2.39158C12.4898 2.40215 13.5856 2.88879 14.4316 3.75779C14.436 3.76227 15.2849 4.63605 15.751 5.7617C15.7598 5.78321 16.2344 6.93916 16.2344 8.19529V8.74998C16.2344 8.74998 16.2346 11.9916 17.252 13.749C17.252 13.749 17.4186 14.0397 17.4189 14.374C17.4189 14.3778 17.4186 14.7099 17.2529 14.998C17.2529 14.998 17.086 15.2881 16.7969 15.456C16.7857 15.4625 16.5015 15.6238 16.1738 15.625H3.82813C3.82813 15.625 3.49126 15.624 3.20215 15.456C3.19969 15.4546 2.91204 15.2866 2.74609 14.998C2.74056 14.9883 2.5798 14.7026 2.58008 14.374C2.58008 14.374 2.57998 14.0395 2.74707 13.75C2.74707 13.75 3.76563 11.9919 3.76563 8.74998V8.12498C3.76562 8.1128 3.7659 6.87303 4.24121 5.72654C4.24121 5.72654 4.7189 4.57443 5.60254 3.69432C5.60254 3.69432 6.4865 2.81373 7.64063 2.3408C7.64063 2.3408 8.79482 1.86812 10.042 1.87498ZM10.0352 3.12498C10.0198 3.12492 9.03102 3.12288 8.11523 3.49803C8.11523 3.49803 7.19216 3.87624 6.48535 4.58006C6.48535 4.58006 5.77856 5.28373 5.39648 6.20506C5.39648 6.20506 5.01425 7.12661 5.01563 8.12498V8.74998C5.01563 8.74998 5.01534 12.3276 3.83008 14.375H16.1689C16.1533 14.3478 14.9844 12.3032 14.9844 8.74998V8.19529C14.9844 8.17955 14.9783 6.11138 13.5361 4.62987C13.5361 4.62987 12.0867 3.14053 10.0352 3.12498Z" fill="currentColor"/>
              <path d="M13.125 15.625V15C13.125 14.6548 12.8452 14.375 12.5 14.375C12.1548 14.375 11.875 14.6548 11.875 15V15.625C11.875 16.4016 11.3258 16.9508 11.3258 16.9508C10.7766 17.5 10 17.5 10 17.5C9.22335 17.5 8.67417 16.9508 8.67417 16.9508C8.125 16.4016 8.125 15.625 8.125 15.625V15C8.125 14.6548 7.84518 14.375 7.5 14.375C7.15482 14.375 6.875 14.6548 6.875 15L6.875 15.625C6.875 16.9194 7.79029 17.8347 7.79029 17.8347C8.70558 18.75 10 18.75 10 18.75C11.2944 18.75 12.2097 17.8347 12.2097 17.8347C13.125 16.9194 13.125 15.625 13.125 15.625Z" fill="currentColor"/>
              </svg>
              {unreadCount > 0 ? (
                <span className="absolute -right-0.5 -top-0.5 inline-flex min-w-[16px] items-center justify-center rounded-full bg-red-500 px-1 text-[10px] font-semibold leading-4 text-white">
                  {unreadCount > 9 ? "9+" : unreadCount}
                </span>
              ) : null}
            </Button>
            {notifOpen ? (
              <div className="absolute right-0 top-11 z-50 w-[340px] rounded-lg border bg-popover shadow-lg">
                <div className="flex items-center justify-between border-b px-3 py-2">
                  <div className="text-sm font-semibold text-foreground">Notifications</div>
                  <button
                    type="button"
                    className="text-xs text-blue-600 hover:underline"
                    onClick={async () => {
                      try {
                        await notificationsApi.markAllRead()
                        await loadNotifications()
                      } catch {}
                    }}
                  >
                    Mark all read
                  </button>
                </div>
                <div className="max-h-80 overflow-auto">
                  {notifLoading ? (
                    <div className="px-3 py-3 text-xs text-muted-foreground">Loading...</div>
                  ) : notifications.filter((n) => !n.is_read).length === 0 ? (
                    <div className="px-3 py-3 text-xs text-muted-foreground">No notifications yet.</div>
                  ) : (
                    notifications
                      .filter((n) => !n.is_read)
                      .map((n) => (
                      <button
                        key={n.id}
                        type="button"
                        onClick={() => openNotificationRef(n)}
                        className={cn(
                          "w-full border-b px-3 py-2 text-left hover:bg-accent/60",
                          !n.is_read && "bg-blue-50/60 dark:bg-blue-950/20"
                        )}
                      >
                        <div className="text-xs font-semibold text-foreground">{n.title}</div>
                        {n.message ? (
                          <div className="mt-0.5 line-clamp-2 text-xs text-muted-foreground">{n.message}</div>
                        ) : null}
                        <div className="mt-1 text-[10px] text-muted-foreground">
                          {new Date(n.created_at.endsWith("Z") ? n.created_at : n.created_at + "Z").toLocaleString()}
                        </div>
                      </button>
                    ))
                  )}
                </div>
              </div>
            ) : null}
          </div>
          <div className="relative" ref={profileMenuRef}>
            {isProfileMenuOpen ? (
              <div className="absolute right-0 top-11 z-50 w-[220px] rounded-lg border bg-card p-1 shadow-lg">
                <button
                  type="button"
                  onClick={handleOpenProfile}
                  className="flex h-9 w-full items-center rounded-md px-3 text-left text-sm text-foreground hover:bg-accent"
                >
                  Profile
                </button>
                <button
                  type="button"
                  onClick={handleLogout}
                  className="flex h-9 w-full items-center rounded-md px-3 text-left text-sm text-foreground hover:bg-accent"
                >
                  Logout
                </button>
              </div>
            ) : null}
            <button
              type="button"
              onClick={() => setIsProfileMenuOpen((prev) => !prev)}
              className="flex h-9 items-center gap-2 rounded-lg px-2 py-0.5 hover:bg-accent"
              aria-haspopup="menu"
              aria-expanded={isProfileMenuOpen}
              title="Open Profile Menu"
            >
              <div className="grid h-6 w-6 shrink-0 place-items-center rounded-full bg-muted text-xs font-semibold text-foreground">
                {currentUser.initial}
              </div>
              <span className="hidden max-w-[140px] truncate text-sm text-foreground sm:inline">
                {currentUser.name}
              </span>
            </button>
          </div>
        </div>
      </div>
      {isHelpOpen && (
        <ReportIssueModal
          onClose={() => setIsHelpOpen(false)}
          currentUserInfo={rawUserInfo}
        />
      )}
    </header>
  )
}
