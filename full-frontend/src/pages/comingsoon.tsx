import { useLocation } from "react-router-dom"

import { MainLayout } from "@/components/layout/MainLayout"

function humanizePath(pathname: string) {
  const p = pathname.replace(/^\/+/, "").replace(/[-_/]+/g, " ").trim()
  if (!p) return "Page"
  return p
    .split(" ")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ")
}

export default function ComingSoonPage() {
  const { pathname } = useLocation()
  const title = humanizePath(pathname)

  return (
    <MainLayout
      header={{
        breadcrumbs: [{ label: "ComplyCore", to: "/dashboard/default" }, { label: title }],
      }}
    >
      <div className="rounded-xl border bg-card p-6">
        <div className="text-lg font-semibold text-foreground">{title}</div>
        <div className="mt-2 text-sm text-muted-foreground">
          This page is wired into the sidebar, but the content is not implemented yet.
        </div>
      </div>
    </MainLayout>
  )
}

