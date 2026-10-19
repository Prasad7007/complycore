import * as React from "react"
import { Outlet, useLocation, useNavigate } from "react-router-dom"

import { Header, type HeaderProps } from "@/components/layout/Header"

export type AppShellContextValue = {
  isDesktop: boolean
  desktopSidebarCollapsed: boolean
  mobileSidebarOpen: boolean
  onToggleSidebar: () => void
}

const AppShellContext = React.createContext<AppShellContextValue | null>(null)

export function useAppShell(): AppShellContextValue | null {
  return React.useContext(AppShellContext)
}

export type HeaderConfig = Pick<
  HeaderProps,
  | "breadcrumbs"
  | "onUploadClick"
  | "className"
  | "searchQuery"
  | "onSearchChange"
  | "searchPlaceholder"
>

type HeaderConfigContextValue = {
  setConfig: (cfg: HeaderConfig | null) => void
}

const HeaderConfigContext = React.createContext<HeaderConfigContextValue>({
  setConfig: () => {},
})

export function useHeaderConfig(): HeaderConfigContextValue {
  return React.useContext(HeaderConfigContext)
}

function useMediaQuery(query: string) {
  const [matches, setMatches] = React.useState(() => {
    if (typeof window === "undefined") return false
    return window.matchMedia(query).matches
  })

  React.useEffect(() => {
    const mql = window.matchMedia(query)
    const onChange = (e: MediaQueryListEvent) => setMatches(e.matches)
    setMatches(mql.matches)
    mql.addEventListener("change", onChange)
    return () => mql.removeEventListener("change", onChange)
  }, [query])

  return matches
}

function isHeaderConfigEqual(a: HeaderConfig | null, b: HeaderConfig | null): boolean {
  if (a === b) return true
  if (!a || !b) return false
  if (a.searchQuery !== b.searchQuery) return false
  if (a.searchPlaceholder !== b.searchPlaceholder) return false
  if (a.className !== b.className) return false
  if (a.onSearchChange !== b.onSearchChange) return false
  if (a.onUploadClick !== b.onUploadClick) return false
  const aCrumbs = a.breadcrumbs
  const bCrumbs = b.breadcrumbs
  if (aCrumbs === bCrumbs) return true
  if (!aCrumbs || !bCrumbs) return false
  if (aCrumbs.length !== bCrumbs.length) return false
  for (let i = 0; i < aCrumbs.length; i++) {
    if (aCrumbs[i].label !== bCrumbs[i].label) return false
    if (aCrumbs[i].to !== bCrumbs[i].to) return false
  }
  return true
}

/**
 * Persistent application shell. The header, scrollable main, and footer are
 * mounted ONCE here so they do not re-mount (and re-fetch their data) on every
 * navigation. Pages register their per-route header config (breadcrumbs,
 * search bar wiring, upload handler) via {@link useHeaderConfig}, which is
 * driven by `MainLayout`.
 */
export function AppShell() {
  const isDesktop = useMediaQuery("(min-width: 1024px)")
  const desktopSidebarCollapsed = true
  const mobileSidebarOpen = false
  const onToggleSidebar = React.useCallback(() => {}, [])

  const ctx = React.useMemo<AppShellContextValue>(
    () => ({ isDesktop, desktopSidebarCollapsed, mobileSidebarOpen, onToggleSidebar }),
    [isDesktop, desktopSidebarCollapsed, mobileSidebarOpen, onToggleSidebar]
  )

  const [headerConfig, setHeaderConfigState] = React.useState<HeaderConfig | null>(null)

  const setConfig = React.useCallback((cfg: HeaderConfig | null) => {
    setHeaderConfigState((prev) => (isHeaderConfigEqual(prev, cfg) ? prev : cfg))
  }, [])

  const headerCtx = React.useMemo<HeaderConfigContextValue>(
    () => ({ setConfig }),
    [setConfig]
  )

  const location = useLocation()
  const navigate = useNavigate()

  // Routes that opt out of the standard chrome (header + scrollable main + footer).
  const isFullScreenRoute = location.pathname === "/pending-access"

  const defaultUploadClick = React.useCallback(() => {
    const returnTo = `${location.pathname}${location.search}`
    navigate("/upload-document", {
      state: { returnTo: returnTo === "/upload-document" ? "/validate-documents" : returnTo },
    })
  }, [navigate, location.pathname, location.search])

  const resolvedUploadClick = headerConfig?.onUploadClick ?? defaultUploadClick

  return (
    <AppShellContext.Provider value={ctx}>
      <HeaderConfigContext.Provider value={headerCtx}>
        <div className="h-screen overflow-hidden">
          <div className="flex h-screen">
            <div className="min-w-0 flex-1 flex flex-col h-screen relative bg-[radial-gradient(circle_at_bottom_right,rgba(135,206,250,0.6),rgba(135,206,250,0.3)_35%,rgba(135,206,250,0.12)_60%,transparent_100%)] dark:bg-[radial-gradient(circle_at_bottom_right,rgba(30,58,138,0.35),rgba(30,58,138,0.12)_35%,rgba(30,58,138,0.04)_65%,transparent_100%),hsl(240,10%,6%)]">
              {isFullScreenRoute ? (
                <Outlet />
              ) : (
                <>
                  <Header
                    breadcrumbs={headerConfig?.breadcrumbs}
                    className={headerConfig?.className}
                    onUploadClick={resolvedUploadClick}
                    searchQuery={headerConfig?.searchQuery}
                    onSearchChange={headerConfig?.onSearchChange}
                    searchPlaceholder={headerConfig?.searchPlaceholder}
                  />
                  <main className="flex min-h-0 flex-1 flex-col overflow-y-auto px-6 py-6">
                    <Outlet />
                  </main>
                  <footer className="shrink-0 px-6 py-3 border-t bg-background/50 backdrop-blur-sm">
                    <p className="text-xs text-muted-foreground">
                      &copy; {new Date().getFullYear()} AI Compliance
                    </p>
                  </footer>
                </>
              )}
            </div>
          </div>
        </div>
      </HeaderConfigContext.Provider>
    </AppShellContext.Provider>
  )
}
