import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"

import { cn } from "@/lib/utils"

const badgeVariants = cva(
  // Whitespace-nowrap: Badges should never wrap.
  "whitespace-nowrap inline-flex items-center rounded-md border px-2.5 py-1 text-[11px] font-semibold tracking-[0.08em] uppercase transition-colors focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-0" +
  " hover-elevate " ,
  {
    variants: {
      variant: {
        default:
          "border-primary/20 bg-primary/18 text-primary shadow-xs",
        secondary: "border-white/10 bg-white/[0.05] text-secondary-foreground",
        destructive:
          "border-destructive/20 bg-destructive/15 text-destructive-foreground shadow-xs",

        outline: "border [border-color:var(--badge-outline)] bg-transparent text-foreground/76 shadow-xs",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  },
)

export interface BadgeProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, ...props }: BadgeProps) {
  return (
    <div className={cn(badgeVariants({ variant }), className)} {...props} />
  );
}

export { Badge, badgeVariants }
