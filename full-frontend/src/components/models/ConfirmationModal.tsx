import * as React from "react"
import { createPortal } from "react-dom"
import { X } from "lucide-react"

export type ConfirmationModalProps = {
    isOpen: boolean
    title: string
    message: string
    confirmText?: string
    cancelText?: string
    onConfirm: () => void
    onCancel: () => void
    isDanger?: boolean
}

export function ConfirmationModal({
    isOpen,
    title,
    message,
    confirmText = "Confirm",
    cancelText = "Cancel",
    onConfirm,
    onCancel,
    isDanger = false,
}: ConfirmationModalProps) {
    if (!isOpen) return null
    if (typeof document === "undefined") return null

    return createPortal(
        <div
            className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/20 backdrop-blur-sm"
            role="dialog"
            aria-modal="true"
        >
            <div className="w-full max-w-sm rounded-xl border border-border bg-card p-6 shadow-xl dark:bg-[#1e293b]">
                <div className="flex items-start justify-between">
                    <h3 className="text-lg font-semibold text-foreground">{title}</h3>
                    <button
                        type="button"
                        onClick={onCancel}
                        className="rounded-md p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
                    >
                        <X className="h-4 w-4" />
                    </button>
                </div>
                <div className="mt-3">
                    <p className="text-sm text-muted-foreground leading-relaxed">{message}</p>
                </div>
                <div className="mt-6 flex justify-end gap-3">
                    <button
                        type="button"
                        className="rounded-lg border border-input px-4 py-2 text-sm font-medium text-foreground hover:bg-muted"
                        onClick={onCancel}
                    >
                        {cancelText}
                    </button>
                    <button
                        type="button"
                        className={`rounded-lg px-4 py-2 text-sm font-medium text-white shadow-sm hover:opacity-90 transition-opacity ${
                            isDanger 
                            ? "bg-red-600 hover:bg-red-700" 
                            : "bg-gradient-to-r from-[#128ADA] to-[#662CC4]"
                        }`}
                        onClick={onConfirm}
                    >
                        {confirmText}
                    </button>
                </div>
            </div>
        </div>,
        document.body
    )
}
