/**
 * Role-to-route rules aligned with `Sidebar.tsx` nav visibility.
 * Used for client-side route guards (API remains authoritative).
 */

const DOC_WORKFLOW_ROLES = new Set(["marketing", "sme", "compliance", "super_admin"])
const SOCIAL_ROLES = new Set(["compliance", "super_admin"])
const SOCIAL_SETTINGS_ROLES = new Set(["compliance", "super_admin"])
const SUPER_ADMIN_ONLY = new Set(["super_admin"])
const OWNER_ONLY = new Set(["owner"])

function roleSet(roleList: string[]) {
  return new Set(roleList)
}

function hasAny(roles: Set<string>, allowed: Set<string>) {
  for (const r of roles) {
    if (allowed.has(r)) return true
  }
  return false
}

/** First app screen after login / when redirecting from a forbidden URL. */
export function getHomePathForRoles(roleList: string[], orgSlug?: string | null): string {
  const roles = roleSet(roleList)
  if (hasAny(roles, OWNER_ONLY)) return "/owner/multitenancy"
  const prefix = orgSlug ? `/orgs/${encodeURIComponent(orgSlug)}` : ""
  if (hasAny(roles, DOC_WORKFLOW_ROLES)) return prefix ? `${prefix}/dashboard/default` : "/dashboard/default"
  return prefix ? `${prefix}/dashboard/default` : "/dashboard/default"
}

/**
 * Whether the current user may open this pathname (under RequireAppAccessLayout).
 * `/pending-access` is allowed for incomplete profiles handled separately.
 */
export function pathnameAllowedForRoles(pathname: string, roleList: string[]): boolean {
  const roles = roleSet(roleList)

  if (pathname === "/pending-access") return true

  if (pathname.startsWith("/owner")) {
    return hasAny(roles, OWNER_ONLY)
  }

  if (pathname.startsWith("/super-admin") || pathname.startsWith("/user-roles")) {
    return hasAny(roles, SUPER_ADMIN_ONLY)
  }

  if (/^\/orgs\/[^/]+\/social-media-settings/.test(pathname)) {
    return hasAny(roles, SOCIAL_SETTINGS_ROLES)
  }

  if (/^\/orgs\/[^/]+\/social-media/.test(pathname)) {
    return hasAny(roles, SOCIAL_ROLES)
  }

  if (pathname.startsWith("/social-media-settings")) {
    return hasAny(roles, SOCIAL_SETTINGS_ROLES)
  }

  if (pathname.startsWith("/social-media")) {
    return hasAny(roles, SOCIAL_ROLES)
  }

  if (
    /^\/orgs\/[^/]+\/(validate-documents|upload-document|published-documents|reports|audit-trail|dashboard)/.test(
      pathname
    )
  ) {
    return hasAny(roles, DOC_WORKFLOW_ROLES)
  }

  if (pathname.startsWith("/dashboard") || pathname.startsWith("/activities")) {
    return hasAny(roles, DOC_WORKFLOW_ROLES)
  }

  if (
    pathname.startsWith("/validate-documents") ||
    pathname.startsWith("/upload-document") ||
    pathname.startsWith("/published-documents") ||
    pathname.startsWith("/reports") ||
    pathname.startsWith("/audit-trail")
  ) {
    return hasAny(roles, DOC_WORKFLOW_ROLES)
  }

  return true
}
