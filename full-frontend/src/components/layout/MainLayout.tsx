import * as React from "react"

import { type HeaderProps } from "@/components/layout/Header"
import { useHeaderConfig } from "@/components/layout/AppShell"

export type MainLayoutProps = {
  children: React.ReactNode
  header?: Pick<
    HeaderProps,
    | "breadcrumbs"
    | "onUploadClick"
    | "className"
    | "searchQuery"
    | "onSearchChange"
    | "searchPlaceholder"
  >
  /** @deprecated MainLayout no longer renders a wrapper element. */
  className?: string
}

/**
 * Per-page registration helper for the persistent app chrome.
 *
 * The Header, scrollable main area, and footer live in {@link AppShell} so
 * they stay mounted across navigations (no Header re-fetch, no notification
 * stream reconnect, no flash of "Loading..."). Pages keep using `<MainLayout>`
 * to declare their per-route header config (breadcrumbs, search wiring,
 * upload handler); this component only registers that config and renders the
 * page content into the shell's main slot.
 */
export function MainLayout({ children, header }: MainLayoutProps) {
  const { setConfig } = useHeaderConfig()

  const breadcrumbs = header?.breadcrumbs
  const onUploadClick = header?.onUploadClick
  const className = header?.className
  const searchQuery = header?.searchQuery
  const onSearchChange = header?.onSearchChange
  const searchPlaceholder = header?.searchPlaceholder

  React.useLayoutEffect(() => {
    setConfig({
      breadcrumbs,
      onUploadClick,
      className,
      searchQuery,
      onSearchChange,
      searchPlaceholder,
    })
  }, [
    breadcrumbs,
    onUploadClick,
    className,
    searchQuery,
    onSearchChange,
    searchPlaceholder,
    setConfig,
  ])

  return <>{children}</>
}
