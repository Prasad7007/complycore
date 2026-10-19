import * as React from "react"
import { Navigate, Outlet, useLocation } from "react-router-dom"

import { fetchUserMeFresh } from "@/lib/api"
import { getHomePathForRoles, pathnameAllowedForRoles } from "@/lib/role-routes"

type MeResponse = {
  access_ready?: boolean
  roles?: string[]
  pending_org_invite?: boolean
  organization?: { id?: string; slug?: string; name?: string } | null
}

function isAdminishPath(pathname: string) {
  return pathname.startsWith("/super-admin") || pathname.startsWith("/user-roles")
}

export function RequireAppAccessLayout() {
  const location = useLocation()
  const [status, setStatus] = React.useState<"loading" | "ok" | "pending" | "unauth">("loading")
  const [userRoles, setUserRoles] = React.useState<string[]>([])
  const [orgSlug, setOrgSlug] = React.useState<string | null>(null)

  React.useEffect(() => {
    let cancelled = false
    const run = async () => {
      // Session is held in an httpOnly cookie that JS cannot see; rely on the
      // server to tell us whether we're authenticated by trying /users/me.
      try {
        const me = (await fetchUserMeFresh<MeResponse>()) as MeResponse
        if (cancelled) return
        const roleList = Array.isArray(me?.roles) ? [...me.roles] : []
        setUserRoles(roleList)
        const roles = new Set(roleList)
        setOrgSlug(me?.organization?.slug ? String(me.organization.slug) : null)

        if (roles.has("owner")) {
          setStatus("ok")
          return
        }

        if (me?.pending_org_invite) {
          setStatus("pending")
          return
        }

        const ready = Boolean(me?.access_ready)
        if (ready) {
          setStatus("ok")
          return
        }
        if (isAdminishPath(location.pathname) && roles.has("super_admin")) {
          setStatus("ok")
          return
        }
        setStatus("pending")
      } catch {
        if (!cancelled) setStatus("unauth")
      }
    }
    void run()
    return () => {
      cancelled = true
    }
  }, [location.pathname])

  if (status === "unauth") {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />
  }
  if (status === "loading") {
    return (
      <div className="flex min-h-[40vh] items-center justify-center text-sm text-muted-foreground">
        Loading…
      </div>
    )
  }
  if (status === "pending") {
    if (location.pathname === "/pending-access") {
      return <Outlet />
    }
    return <Navigate to="/pending-access" replace />
  }

  const home = getHomePathForRoles(userRoles, orgSlug)

  if (location.pathname === "/pending-access") {
    return <Navigate to={home} replace />
  }

  if (!pathnameAllowedForRoles(location.pathname, userRoles)) {
    return <Navigate to={home} replace />
  }

  return <Outlet />
}
