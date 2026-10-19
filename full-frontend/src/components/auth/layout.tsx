import * as React from "react"
import { cn } from "@/lib/utils"

export type AuthSplitLayoutProps = {
  brand?: React.ReactNode
  title?: string
  subtitle?: string
  titleOutside?: boolean
  children: React.ReactNode
  imageSrc?: string
  imageAlt?: string
  imageSide?: "left" | "right"
  bottomCta?: React.ReactNode
  className?: string
}

export function AuthSplitLayout({
  brand,
  title,
  subtitle,
  titleOutside = false,
  children,
  imageSrc,
  imageAlt = "auth",
  imageSide = "left",
  bottomCta,
  className,
}: AuthSplitLayoutProps) {
  const [showBgImage, setShowBgImage] = React.useState(true)

  return (
    <div className={cn("relative flex h-screen overflow-hidden bg-background", className)}>

      {/* Full-screen background image (small screens only) */}
      {imageSrc && showBgImage && (
        <div className="absolute inset-0 lg:hidden">
          <img
            src={imageSrc}
            alt={imageAlt}
            className="h-full w-full object-cover"
            onError={() => setShowBgImage(false)}
          />
        </div>
      )}

      {/* IMAGE SIDE — large screens only */}
      <div
        className={cn(
          "relative hidden w-1/2 flex-shrink-0 overflow-hidden lg:block",
          imageSide === "right" ? "order-2" : "order-1"
        )}
      >
        <div className="absolute inset-0 bg-gradient-to-br from-violet-950 via-indigo-950 to-fuchsia-900" />
        {imageSrc && showBgImage && (
          <img
            src={imageSrc}
            alt={imageAlt}
            className="absolute inset-0 h-full w-full object-cover"
          />
        )}
        <div className="absolute inset-0 bg-black/10" />
      </div>

      {/* FORM SIDE */}
      <div
        className={cn(
          "relative flex w-full flex-col overflow-y-auto bg-transparent lg:w-1/2 lg:bg-white",
          imageSide === "right" ? "order-1" : "order-2"
        )}
      >
        {/* Logo — pinned top-left */}
        {brand && (
          <div className="flex-shrink-0 px-12 pt-10">
            {brand}
          </div>
        )}

        {/* Title outside — aligned with logo text ("ComplyCore"), not the icon */}
        {title && titleOutside && (
          <div className={cn("pl-24 pr-12", subtitle ? "pb-8" : "pb-10")}>
            <h2 className="text-[22px] font-bold leading-tight text-foreground">
              {title}
            </h2>
            {subtitle && (
              <p className="mt-1.5 text-sm text-muted-foreground">{subtitle}</p>
            )}
          </div>
        )}

        {/* Form content — centered */}
        <div className="flex flex-1 items-start justify-center px-4 pt-6 pb-6 lg:px-12 lg:pt-10">
          <div className="w-full max-w-[360px] rounded-2xl bg-white/85 p-6 backdrop-blur-sm lg:rounded-none lg:bg-transparent lg:p-0 lg:backdrop-blur-none">
            {title && !titleOutside && (
              <div className={subtitle ? "mb-8" : "mb-10"}>
                <h2 className="text-[22px] font-semibold leading-tight text-foreground">
                  {title}
                </h2>
                {subtitle && (
                  <p className="mt-1.5 text-sm text-muted-foreground">
                    {subtitle}
                  </p>
                )}
              </div>
            )}
            {children}
          </div>
        </div>

        {/* Bottom CTA — pinned to bottom */}
        {bottomCta && (
          <div className="flex-shrink-0 flex justify-center pb-8 pt-2">
            {bottomCta}
          </div>
        )}
      </div>

    </div>
  )
}

export default AuthSplitLayout
