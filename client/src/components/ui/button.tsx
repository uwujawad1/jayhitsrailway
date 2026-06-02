import * as React from "react"
import { Slot } from "@radix-ui/react-slot"
import { cva, type VariantProps } from "class-variance-authority"

import { cn } from "@/lib/utils"

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-lg border text-sm font-semibold focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/70 focus-visible:ring-offset-0 disabled:pointer-events-none disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:size-4 [&_svg]:shrink-0 shadow-sm hover:-translate-y-0.5 hover-elevate active-elevate-2",
  {
    variants: {
      variant: {
        default:
          "border-primary/30 bg-[linear-gradient(135deg,hsl(var(--primary))_0%,hsl(158_42%_40%)_100%)] text-primary-foreground shadow-[0_18px_34px_rgba(84,214,165,0.18)]",
        destructive:
          "border-destructive/30 bg-[linear-gradient(135deg,hsl(var(--destructive))_0%,hsl(4_60%_48%)_100%)] text-destructive-foreground shadow-[0_18px_34px_rgba(210,82,70,0.14)]",
        outline:
          "border-white/12 bg-white/[0.04] text-foreground/88 shadow-none backdrop-blur-sm hover:bg-white/[0.08]",
        secondary:
          "border-white/8 bg-[linear-gradient(180deg,rgba(255,255,255,0.055),rgba(255,255,255,0.02))] text-secondary-foreground hover:bg-white/[0.08]",
        ghost:
          "border-transparent bg-transparent text-foreground/78 shadow-none hover:bg-white/[0.06] hover:text-foreground",
      },
      // Heights are set as "min" heights, because sometimes Ai will place large amount of content
      // inside buttons. With a min-height they will look appropriate with small amounts of content,
      // but will expand to fit large amounts of content.
      size: {
        default: "min-h-10 px-4 py-2.5",
        sm: "min-h-8 px-3 text-xs",
        lg: "min-h-11 px-6 text-sm",
        icon: "h-10 w-10",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  },
)

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, ...props }, ref) => {
    const Comp = asChild ? Slot : "button"
    return (
      <Comp
        className={cn(buttonVariants({ variant, size, className }))}
        ref={ref}
        {...props}
      />
    )
  },
)
Button.displayName = "Button"

export { Button, buttonVariants }
