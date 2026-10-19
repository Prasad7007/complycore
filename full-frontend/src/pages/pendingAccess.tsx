import { useNavigate } from "react-router-dom"

import { AiComplianceMark } from "@/components/brand/AiComplianceMark"
import { Button } from "@/components/ui/button"
import { authApi } from "@/lib/api"

export default function PendingAccessPage() {
  const navigate = useNavigate()

  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-6 bg-background px-4">
      <AiComplianceMark className="h-12 w-auto" />
      <div className="max-w-md text-center">
        <h1 className="text-xl font-semibold text-foreground">Access pending</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          Your administrator must assign your department and at least one role before you can use the
          application. You will be redirected automatically once setup is complete.
        </p>
      </div>
      <Button
        type="button"
        variant="default"
        className="bg-[#1F4ED8] hover:bg-[#1F4ED8]/90"
        onClick={async () => {
          // Cookie is httpOnly so the server must clear it.
          await authApi.logout().catch(() => undefined)
          navigate("/login", { replace: true })
        }}
      >
        Sign out
      </Button>
    </div>
  )
}
