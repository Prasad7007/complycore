import * as React from "react"

import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import type { DocumentStatus } from "@/components/layout/document-preview-card"
import { FileIcon } from "@/components/icons/FileIcon"

export type DocumentTab = "preview" | "trail"

type CommonHeaderCardCustomProps = {
  className?: string
  children: React.ReactNode
}

type CommonHeaderCardTabsProps = {
  /** Currently active tab */
  activeTab: DocumentTab
  /** Called when user switches tab */
  onTabChange: (tab: DocumentTab) => void
  /** When true, show both tabs (Preview + Trail). Default is only active tab. */
  showBothTabs?: boolean
  /**
   * Controls which single pill is displayed when `showBothTabs` is false.
   * Defaults to `activeTab`.
   */
  displayTab?: DocumentTab
  /** When true, hides the left-side tab/pill area (right actions only). */
  hideLeftTabs?: boolean
  /** Called when "Claim Review" button is clicked */
  onClaimReview?: () => void
  /** When true, shows Approve/Request/Reject actions instead of Claim */
  claimed?: boolean
  /** Document status used for post-approval header state */
  status?: DocumentStatus
  /** Optional comment trail count badge */
  trailCount?: number
  onApprove?: () => void
  onRequestChanges?: () => void
  onReject?: () => void
  onUploadNewVersion?: () => void
  approveButtonText?: string
  isApproveDisabled?: boolean
  approveDisabledTooltip?: string
  isClaimDisabled?: boolean
  claimDisabledTooltip?: string
  versions?: Array<{ id: string; label: string; [key: string]: any }>
  currentVersionId?: string
  onVersionChange?: (versionId: string) => void
  className?: string
  children?: never
}

export type CommonHeaderCardProps = CommonHeaderCardCustomProps | CommonHeaderCardTabsProps

export function CommonHeaderCard(props: CommonHeaderCardProps) {
  if ("children" in props) {
    return (
      <div
        className={cn(
          "rounded-xl bg-card shadow-[-4px_4px_12px_rgba(16,24,40,0.08)] dark:shadow-[-4px_4px_12px_rgba(0,0,0,0.35)]",
          props.className
        )}
      >
        {props.children}
      </div>
    )
  }

  const {
    activeTab,
    onTabChange,
    onClaimReview,
    claimed,
    onApprove,
    onRequestChanges,
    onReject,
    approveButtonText = "Approve",
    className,
  } = props

  const showBothTabs = props.showBothTabs ?? false
  const displayTab = props.displayTab ?? activeTab

  return (
    <div
      className={cn(
        "flex flex-wrap items-center justify-between gap-x-6 gap-y-0 rounded-xl bg-card px-5 min-h-[56px] shadow-[-4px_4px_12px_rgba(16,24,40,0.08)] dark:shadow-[-4px_4px_12px_rgba(0,0,0,0.35)]",
        className
      )}
    >
      {/* ── Tabs ── */}
      <div className="flex items-center gap-2 py-3">
          {showBothTabs || displayTab === "preview" ? (
            <button
              type="button"
              onClick={() => onTabChange("preview")}
              className={cn(
                "flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium transition-all whitespace-nowrap bg-muted text-foreground",
                activeTab === "preview"
                  ? "font-semibold shadow-sm"
                  : "opacity-90 hover:opacity-100"
              )}
            >
              <FileIcon className="h-4 w-4 shrink-0" />
              <span className="hidden sm:inline">Document Preview</span>
              <span className="sm:hidden">Preview</span>
            </button>
          ) : null}

          {showBothTabs ? (
            /* Both tabs visible: show "Comment Trail" as the second tab normally */
            <button
              type="button"
              onClick={() => onTabChange("trail")}
              className={cn(
                "flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium transition-all whitespace-nowrap bg-muted text-foreground",
                activeTab === "trail"
                  ? "font-semibold shadow-sm"
                  : "opacity-90 hover:opacity-100"
              )}
            >
              <img src="/shared/chatIcon.svg" alt="" className="h-5 w-5 shrink-0 dark:invert dark:opacity-90" />
              <span className="hidden sm:inline">Comments &amp; Discussion</span>
              <span className="sm:hidden">Trail</span>
              {typeof props.trailCount === "number" && props.trailCount > 0 ? (
                <span className="grid h-5 min-w-[20px] place-items-center rounded-full bg-emerald-600 px-1.5 text-[11px] font-semibold text-white">
                  {props.trailCount}
                </span>
              ) : null}
            </button>
          ) : displayTab === "trail" ? (
            /* Single tab visible and currently on trail: show "Document Preview" to navigate back */
            <button
              type="button"
              onClick={() => onTabChange("preview")}
              className={cn(
                "flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium transition-all whitespace-nowrap bg-muted text-foreground",
                "opacity-90 hover:opacity-100"
              )}
            >
              <FileIcon className="h-4 w-4 shrink-0" />
              <span className="hidden sm:inline">Document Preview</span>
              <span className="sm:hidden">Preview</span>
            </button>
          ) : null}
          {props.onUploadNewVersion ? (
            <Button
              type="button"
              onClick={props.onUploadNewVersion}
              variant="secondary"
              className="gap-1.5 rounded-lg text-sm font-medium h-9 px-4 sm:px-5 whitespace-nowrap"
            >
              <svg width="16" height="16" viewBox="0 0 18 18" fill="none" xmlns="http://www.w3.org/2000/svg" className="h-4 w-4 shrink-0">
                <path d="M13.6781 12.8961C13.7814 12.9998 13.8394 13.1403 13.8394 13.2867C13.8394 13.4331 13.7814 13.5736 13.6781 13.6773C13.6027 13.7514 11.8202 15.4999 8.85721 15.4999C6.26996 15.4999 4.39197 13.9499 3.3215 12.7425V14.3928C3.3215 14.5396 3.26318 14.6804 3.15936 14.7842C3.05555 14.8881 2.91474 14.9464 2.76793 14.9464C2.62111 14.9464 2.48031 14.8881 2.37649 14.7842C2.27268 14.6804 2.21436 14.5396 2.21436 14.3928V11.0714C2.21436 10.9246 2.27268 10.7838 2.37649 10.6799C2.48031 10.5761 2.62111 10.5178 2.76793 10.5178H6.08936C6.23617 10.5178 6.37697 10.5761 6.48079 10.6799C6.5846 10.7838 6.64293 10.9246 6.64293 11.0714C6.64293 11.2182 6.5846 11.359 6.48079 11.4628C6.37697 11.5666 6.23617 11.6249 6.08936 11.6249H3.83632C4.68882 12.6871 6.43534 14.3928 8.85721 14.3928C11.3483 14.3928 12.8803 12.9079 12.8955 12.8926C12.9998 12.7893 13.1408 12.7317 13.2875 12.7323C13.4343 12.733 13.5748 12.7919 13.6781 12.8961ZM14.9465 2.7678C14.7997 2.7678 14.6589 2.82613 14.5551 2.92994C14.4512 3.03376 14.3929 3.17456 14.3929 3.32138V4.97171C13.3225 3.76423 11.4445 2.21423 8.85721 2.21423C5.89422 2.21423 4.11172 3.96283 4.03699 4.03687C3.93293 4.14056 3.87433 4.28133 3.87407 4.42823C3.87381 4.57513 3.93192 4.71612 4.03561 4.82017C4.13929 4.92423 4.28007 4.98283 4.42697 4.98309C4.57387 4.98335 4.71485 4.92524 4.81891 4.82156C4.83413 4.80633 6.36614 3.32138 8.85721 3.32138C11.2791 3.32138 13.0256 5.02707 13.8781 6.08923H11.6251C11.4783 6.08923 11.3375 6.14756 11.2336 6.25137C11.1298 6.35519 11.0715 6.49599 11.0715 6.64281C11.0715 6.78962 11.1298 6.93042 11.2336 7.03424C11.3375 7.13805 11.4783 7.19638 11.6251 7.19638H14.9465C15.0933 7.19638 15.2341 7.13805 15.3379 7.03424C15.4417 6.93042 15.5001 6.78962 15.5001 6.64281V3.32138C15.5001 3.17456 15.4417 3.03376 15.3379 2.92994C15.2341 2.82613 15.0933 2.7678 14.9465 2.7678Z" fill="currentColor"/>
              </svg>
              <span>Upload New Version</span>
            </Button>
          ) : null}
        </div>

      {/* ── Right actions ── */}
      <div className="flex items-center gap-2 sm:gap-3">
        {props.versions && props.versions.length > 0 && props.onVersionChange ? (
          <select
            className="h-9 rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            value={props.currentVersionId || ""}
            onChange={(e) => props.onVersionChange!(e.target.value)}
          >
            {props.versions.map((v) => (
              <option key={v.id} value={v.id}>
                {v.label}
              </option>
            ))}
          </select>
        ) : null}
        {claimed ? (
          <>
            {props.status === "approved" ? (
              <Button
                type="button"
                className="gap-1.5 rounded-lg bg-[#00C8B3] text-white hover:bg-[#00C8B3]/90 text-xs h-9 px-4 sm:px-5 whitespace-nowrap"
              >
                <svg width="16" height="16" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg" className="h-4 w-4 shrink-0"><path d="M13.5672 7.68281C13.6253 7.74086 13.6714 7.80979 13.7029 7.88566C13.7343 7.96154 13.7505 8.04287 13.7505 8.125C13.7505 8.20713 13.7343 8.28846 13.7029 8.36434C13.6714 8.44021 13.6253 8.50914 13.5672 8.56719L9.19219 12.9422C9.13415 13.0003 9.06522 13.0464 8.98934 13.0779C8.91347 13.1093 8.83214 13.1255 8.75 13.1255C8.66787 13.1255 8.58654 13.1093 8.51067 13.0779C8.43479 13.0464 8.36586 13.0003 8.30782 12.9422L6.43282 11.0672C6.31554 10.9499 6.24966 10.7909 6.24966 10.625C6.24966 10.4591 6.31554 10.3001 6.43282 10.1828C6.55009 10.0655 6.70915 9.99965 6.875 9.99965C7.04086 9.99965 7.19992 10.0655 7.31719 10.1828L8.75 11.6164L12.6828 7.68281C12.7409 7.6247 12.8098 7.5786 12.8857 7.54715C12.9615 7.5157 13.0429 7.49951 13.125 7.49951C13.2071 7.49951 13.2885 7.5157 13.3643 7.54715C13.4402 7.5786 13.5091 7.6247 13.5672 7.68281ZM18.125 10C18.125 11.607 17.6485 13.1779 16.7557 14.514C15.8629 15.8502 14.594 16.8916 13.1093 17.5065C11.6247 18.1215 9.99099 18.2824 8.4149 17.9689C6.8388 17.6554 5.39106 16.8815 4.25476 15.7452C3.11846 14.6089 2.34463 13.1612 2.03112 11.5851C1.71762 10.009 1.87852 8.37535 2.49348 6.8907C3.10844 5.40605 4.14985 4.1371 5.486 3.24431C6.82214 2.35152 8.39303 1.875 10 1.875C12.1542 1.87727 14.2195 2.73403 15.7427 4.25727C17.266 5.78051 18.1227 7.84581 18.125 10ZM16.875 10C16.875 8.64025 16.4718 7.31104 15.7164 6.18045C14.9609 5.04987 13.8872 4.16868 12.631 3.64833C11.3747 3.12798 9.99238 2.99183 8.65876 3.2571C7.32514 3.52237 6.10013 4.17716 5.13864 5.13864C4.17716 6.10013 3.52238 7.32513 3.2571 8.65875C2.99183 9.99237 3.12798 11.3747 3.64833 12.6309C4.16868 13.8872 5.04987 14.9609 6.18046 15.7164C7.31105 16.4718 8.64026 16.875 10 16.875C11.8227 16.8729 13.5702 16.1479 14.8591 14.8591C16.1479 13.5702 16.8729 11.8227 16.875 10Z" fill="white"/></svg>
                <span>Published</span>
              </Button>
            ) : (
              <>
                {onApprove ? (
                <Button
                  type="button"
                  onClick={onApprove}
                  disabled={props.isApproveDisabled}
                  title={props.approveDisabledTooltip}
                  className="gap-1.5 rounded-lg bg-emerald-600 text-white hover:bg-emerald-600/90 text-xs h-9 px-4 sm:px-5 whitespace-nowrap disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  <svg width="16" height="16" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg" className="h-4 w-4 shrink-0"><path d="M13.5672 7.68281C13.6253 7.74086 13.6714 7.80979 13.7029 7.88566C13.7343 7.96154 13.7505 8.04287 13.7505 8.125C13.7505 8.20713 13.7343 8.28846 13.7029 8.36434C13.6714 8.44021 13.6253 8.50914 13.5672 8.56719L9.19219 12.9422C9.13415 13.0003 9.06522 13.0464 8.98934 13.0779C8.91347 13.1093 8.83214 13.1255 8.75 13.1255C8.66787 13.1255 8.58654 13.1093 8.51067 13.0779C8.43479 13.0464 8.36586 13.0003 8.30782 12.9422L6.43282 11.0672C6.31554 10.9499 6.24966 10.7909 6.24966 10.625C6.24966 10.4591 6.31554 10.3001 6.43282 10.1828C6.55009 10.0655 6.70915 9.99965 6.875 9.99965C7.04086 9.99965 7.19992 10.0655 7.31719 10.1828L8.75 11.6164L12.6828 7.68281C12.7409 7.6247 12.8098 7.5786 12.8857 7.54715C12.9615 7.5157 13.0429 7.49951 13.125 7.49951C13.2071 7.49951 13.2885 7.5157 13.3643 7.54715C13.4402 7.5786 13.5091 7.6247 13.5672 7.68281ZM18.125 10C18.125 11.607 17.6485 13.1779 16.7557 14.514C15.8629 15.8502 14.594 16.8916 13.1093 17.5065C11.6247 18.1215 9.99099 18.2824 8.4149 17.9689C6.8388 17.6554 5.39106 16.8815 4.25476 15.7452C3.11846 14.6089 2.34463 13.1612 2.03112 11.5851C1.71762 10.009 1.87852 8.37535 2.49348 6.8907C3.10844 5.40605 4.14985 4.1371 5.486 3.24431C6.82214 2.35152 8.39303 1.875 10 1.875C12.1542 1.87727 14.2195 2.73403 15.7427 4.25727C17.266 5.78051 18.1227 7.84581 18.125 10ZM16.875 10C16.875 8.64025 16.4718 7.31104 15.7164 6.18045C14.9609 5.04987 13.8872 4.16868 12.631 3.64833C11.3747 3.12798 9.99238 2.99183 8.65876 3.2571C7.32514 3.52237 6.10013 4.17716 5.13864 5.13864C4.17716 6.10013 3.52238 7.32513 3.2571 8.65875C2.99183 9.99237 3.12798 11.3747 3.64833 12.6309C4.16868 13.8872 5.04987 14.9609 6.18046 15.7164C7.31105 16.4718 8.64026 16.875 10 16.875C11.8227 16.8729 13.5702 16.1479 14.8591 14.8591C16.1479 13.5702 16.8729 11.8227 16.875 10Z" fill="white"/></svg>
                    <span>{approveButtonText}</span>
                </Button>
                ) : null}

                {onRequestChanges ? (
                <Button
                  type="button"
                  onClick={onRequestChanges}
                  variant="secondary"
                  className="gap-1.5 rounded-lg text-xs h-9 px-4 sm:px-5 whitespace-nowrap"
                >
                  <svg width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg" className="h-4 w-4 shrink-0"><path d="M14.4999 12.5C14.4999 12.6326 14.4472 12.7598 14.3535 12.8536C14.2597 12.9474 14.1325 13 13.9999 13C13.8673 13 13.7401 12.9474 13.6464 12.8536C13.5526 12.7598 13.4999 12.6326 13.4999 12.5C13.4983 11.0419 12.9183 9.64387 11.8872 8.61277C10.8561 7.58168 9.45809 7.00169 7.99991 7.00003H3.20678L5.35366 9.14628C5.44748 9.2401 5.50018 9.36735 5.50018 9.50003C5.50018 9.63272 5.44748 9.75996 5.35366 9.85378C5.25984 9.9476 5.13259 10.0003 4.99991 10.0003C4.86722 10.0003 4.73998 9.9476 4.64615 9.85378L1.64615 6.85378C1.59967 6.80735 1.56279 6.7522 1.53763 6.6915C1.51246 6.6308 1.49951 6.56574 1.49951 6.50003C1.49951 6.43433 1.51246 6.36926 1.53763 6.30856C1.56279 6.24786 1.59967 6.19272 1.64615 6.14628L4.64615 3.14628C4.73998 3.05246 4.86722 2.99976 4.99991 2.99976C5.13259 2.99976 5.25984 3.05246 5.35366 3.14628C5.44748 3.2401 5.50018 3.36735 5.50018 3.50003C5.50018 3.63272 5.44748 3.75996 5.35366 3.85378L3.20678 6.00003H7.99991C9.72325 6.00185 11.3755 6.68726 12.5941 7.90585C13.8127 9.12444 14.4981 10.7767 14.4999 12.5Z" fill="currentColor"/></svg>
                  <span className="hidden sm:inline">Request Changes</span>
                  <span className="sm:hidden">Request</span>
                </Button>
                ) : null}

                {onReject ? (
                <Button
                  type="button"
                  onClick={onReject}
                  className="gap-1.5 rounded-lg bg-red-500 text-white hover:bg-red-500/90 text-xs h-9 px-4 sm:px-5 whitespace-nowrap"
                >
                  <svg width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg" className="h-4 w-4 shrink-0"><path d="M10.3538 6.35375L8.70688 8L10.3538 9.64625C10.4002 9.6927 10.4371 9.74786 10.4622 9.80855C10.4873 9.86925 10.5003 9.9343 10.5003 10C10.5003 10.0657 10.4873 10.1308 10.4622 10.1914C10.4371 10.2521 10.4002 10.3073 10.3538 10.3538C10.3073 10.4002 10.2521 10.4371 10.1915 10.4622C10.1308 10.4873 10.0657 10.5003 10 10.5003C9.93431 10.5003 9.86925 10.4873 9.80855 10.4622C9.74786 10.4371 9.69271 10.4002 9.64625 10.3538L8 8.70687L6.35375 10.3538C6.3073 10.4002 6.25215 10.4371 6.19145 10.4622C6.13075 10.4873 6.0657 10.5003 6 10.5003C5.93431 10.5003 5.86925 10.4873 5.80855 10.4622C5.74786 10.4371 5.69271 10.4002 5.64625 10.3538C5.5998 10.3073 5.56295 10.2521 5.53781 10.1914C5.51266 10.1308 5.49972 10.0657 5.49972 10C5.49972 9.9343 5.51266 9.86925 5.53781 9.80855C5.56295 9.74786 5.5998 9.6927 5.64625 9.64625L7.29313 8L5.64625 6.35375C5.55243 6.25993 5.49972 6.13268 5.49972 6C5.49972 5.86732 5.55243 5.74007 5.64625 5.64625C5.74007 5.55243 5.86732 5.49972 6 5.49972C6.13268 5.49972 6.25993 5.55243 6.35375 5.64625L8 7.29313L9.64625 5.64625C9.69271 5.59979 9.74786 5.56294 9.80855 5.5378C9.86925 5.51266 9.93431 5.49972 10 5.49972C10.0657 5.49972 10.1308 5.51266 10.1915 5.5378C10.2521 5.56294 10.3073 5.59979 10.3538 5.64625C10.4002 5.6927 10.4371 5.74786 10.4622 5.80855C10.4873 5.86925 10.5003 5.9343 10.5003 6C10.5003 6.0657 10.4873 6.13075 10.4622 6.19145C10.4371 6.25214 10.4002 6.3073 10.3538 6.35375ZM14.5 8C14.5 9.28558 14.1188 10.5423 13.4046 11.6112C12.6903 12.6801 11.6752 13.5132 10.4874 14.0052C9.29973 14.4972 7.99279 14.6259 6.73192 14.3751C5.47104 14.1243 4.31285 13.5052 3.40381 12.5962C2.49477 11.6872 1.8757 10.529 1.6249 9.26809C1.37409 8.00721 1.50282 6.70028 1.99479 5.51256C2.48676 4.32484 3.31988 3.30968 4.3888 2.59545C5.45772 1.88122 6.71442 1.5 8 1.5C9.72335 1.50182 11.3756 2.18722 12.5942 3.40582C13.8128 4.62441 14.4982 6.27665 14.5 8ZM13.5 8C13.5 6.9122 13.1774 5.84883 12.5731 4.94436C11.9687 4.03989 11.1098 3.33494 10.1048 2.91866C9.09977 2.50238 7.9939 2.39346 6.92701 2.60568C5.86011 2.8179 4.8801 3.34172 4.11092 4.11091C3.34173 4.8801 2.8179 5.86011 2.60568 6.927C2.39347 7.9939 2.50238 9.09977 2.91867 10.1048C3.33495 11.1098 4.0399 11.9687 4.94437 12.5731C5.84884 13.1774 6.91221 13.5 8 13.5C9.45819 13.4983 10.8562 12.9184 11.8873 11.8873C12.9184 10.8562 13.4983 9.45818 13.5 8Z" fill="white"/></svg>
                  <span>Reject</span>
                </Button>
                ) : null}
              </>
            )}
          </>
        ) : onClaimReview ? (
          <Button
            type="button"
            onClick={onClaimReview}
            disabled={props.isClaimDisabled}
            title={props.claimDisabledTooltip}
            className="gap-1.5 rounded-lg bg-[#5BC0EB] text-white hover:bg-[#5BC0EB]/90 text-xs h-9 px-4 sm:px-5 whitespace-nowrap disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <svg width="14" height="14" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg" className="shrink-0">
                <path d="M13.5672 7.68281C13.6253 7.74086 13.6714 7.80979 13.7029 7.88566C13.7343 7.96154 13.7505 8.04287 13.7505 8.125C13.7505 8.20713 13.7343 8.28846 13.7029 8.36434C13.6714 8.44021 13.6253 8.50914 13.5672 8.56719L9.19219 12.9422C9.13415 13.0003 9.06522 13.0464 8.98934 13.0779C8.91347 13.1093 8.83214 13.1255 8.75 13.1255C8.66787 13.1255 8.58654 13.1093 8.51067 13.0779C8.43479 13.0464 8.36586 13.0003 8.30782 12.9422L6.43282 11.0672C6.31554 10.9499 6.24966 10.7909 6.24966 10.625C6.24966 10.4591 6.31554 10.3001 6.43282 10.1828C6.55009 10.0655 6.70915 9.99965 6.875 9.99965C7.04086 9.99965 7.19992 10.0655 7.31719 10.1828L8.75 11.6164L12.6828 7.68281C12.7409 7.6247 12.8098 7.5786 12.8857 7.54715C12.9615 7.5157 13.0429 7.49951 13.125 7.49951C13.2071 7.49951 13.2885 7.5157 13.3643 7.54715C13.4402 7.5786 13.5091 7.6247 13.5672 7.68281ZM18.125 10C18.125 11.607 17.6485 13.1779 16.7557 14.514C15.8629 15.8502 14.594 16.8916 13.1093 17.5065C11.6247 18.1215 9.99099 18.2824 8.4149 17.9689C6.8388 17.6554 5.39106 16.8815 4.25476 15.7452C3.11846 14.6089 2.34463 13.1612 2.03112 11.5851C1.71762 10.009 1.87852 8.37535 2.49348 6.8907C3.10844 5.40605 4.14985 4.1371 5.486 3.24431C6.82214 2.35152 8.39303 1.875 10 1.875C12.1542 1.87727 14.2195 2.73403 15.7427 4.25727C17.266 5.78051 18.1227 7.84581 18.125 10ZM16.875 10C16.875 8.64025 16.4718 7.31104 15.7164 6.18045C14.9609 5.04987 13.8872 4.16868 12.631 3.64833C11.3747 3.12798 9.99238 2.99183 8.65876 3.2571C7.32514 3.52237 6.10013 4.17716 5.13864 5.13864C4.17716 6.10013 3.52238 7.32513 3.2571 8.65875C2.99183 9.99237 3.12798 11.3747 3.64833 12.6309C4.16868 13.8872 5.04987 14.9609 6.18046 15.7164C7.31105 16.4718 8.64026 16.875 10 16.875C11.8227 16.8729 13.5702 16.1479 14.8591 14.8591C16.1479 13.5702 16.8729 11.8227 16.875 10Z" fill="white"/>
              </svg>
            <span className="hidden sm:inline">Claim Review</span>
            <span className="sm:hidden">Claim</span>
          </Button>
        ) : null}
      </div>
    </div>
  )
}
