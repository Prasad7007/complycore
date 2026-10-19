import * as React from "react"
import { createPortal } from "react-dom"
import { Check, X } from "lucide-react"

export type PasswordUpdateSuccessModalProps = {
    open: boolean
    onClose: () => void
}

export function PasswordUpdateSuccessModal({ open, onClose }: PasswordUpdateSuccessModalProps) {
    React.useEffect(() => {
        if (!open) return
        const onKeyDown = (e: KeyboardEvent) => {
            if (e.key === "Escape") onClose()
        }
        window.addEventListener("keydown", onKeyDown)
        const prevOverflow = document.body.style.overflow
        document.body.style.overflow = "hidden"
        return () => {
            window.removeEventListener("keydown", onKeyDown)
            document.body.style.overflow = prevOverflow
        }
    }, [open, onClose])

    if (!open || typeof document === "undefined") return null

    return createPortal(
        <div
            className="fixed inset-0 z-[9999] flex items-center justify-center px-4"
            style={{ background: "rgba(11,31,59,0.25)" }}
            role="dialog"
            aria-modal="true"
            aria-label="Password updated successfully"
            onMouseDown={(e) => {
                if (e.target === e.currentTarget) onClose()
            }}
        >
            {/* Modal Card Container */}
            <div
                className="relative flex w-full max-w-[624px] flex-col items-center justify-center gap-4 rounded-[16px] bg-white/90 dark:bg-card/95 p-8 text-center backdrop-blur-xl dark:shadow-[0_24px_80px_rgba(0,0,0,0.4)]"
                style={{
                    height: "448px",
                    boxShadow: "14px 18px 25.8px rgba(28,28,28,0.1)",
                    fontFamily: "Inter, sans-serif",
                }}
                onMouseDown={(e) => e.stopPropagation()}
            >
                {/* Close Icon */}
                <button
                    type="button"
                    onClick={onClose}
                    className="absolute right-6 top-6 grid h-8 w-8 place-items-center rounded-md text-foreground hover:bg-accent hover:text-foreground"
                    style={{ cursor: "pointer" }}
                    aria-label="Close"
                >
                    <X className="h-5 w-5" />
                </button>

                {/* Success Icon */}
                <div
                    className="mb-2 grid place-items-center rounded-lg"
                    style={{
                        width: "63px",
                        height: "63px",
                        backgroundColor: "rgba(31,78,216,0.14)",
                    }}
                >
                    <Check className="h-[27px] w-[37px]" style={{ color: "#1F4ED8" }} strokeWidth={2.5} />
                </div>

                {/* Heading */}
                <h2
                    className="max-w-[377px] font-semibold"
                    style={{
                        fontSize: "24px",
                        lineHeight: "36px",
                        color: "#1F4ED8",
                    }}
                >
                    Password Updated Successfully
                </h2>

                {/* Description */}
                <p
                    className="max-w-[314px] font-normal text-foreground"
                    style={{
                        fontSize: "14px",
                        lineHeight: "20px",
                    }}
                >
                    Your password has been changed successfully. You can now continue using your account.
                </p>

                {/* Close Button */}
                <button
                    type="button"
                    onClick={onClose}
                    className="rounded-lg border border-border bg-background font-medium text-foreground hover:bg-muted"
                    style={{
                        width: "124px",
                        height: "38px",
                        padding: "4px 8px",
                        fontSize: "14px",
                        lineHeight: "20px",
                        cursor: "pointer",
                    }}
                >
                    Close
                </button>
            </div>
        </div>,
        document.body
    )
}