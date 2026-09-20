import { Button as ButtonPrimitive } from "@base-ui/react/button"
import { cva, type VariantProps } from "class-variance-authority"
import { cn } from "@/lib/utils"

/**
 * The set's one button vocabulary: square (2px) corners, hairline edges,
 * graphite ink for the primary action, revision red only for changing or
 * undoing the plan. 44px touch height on small screens.
 */
const buttonVariants = cva(
  "group/button inline-flex shrink-0 cursor-pointer items-center justify-center gap-2 rounded-[2px] border border-transparent text-sm font-semibold whitespace-nowrap transition-colors duration-150 outline-none select-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ink disabled:pointer-events-none disabled:opacity-45 aria-busy:cursor-progress [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
  {
    variants: {
      variant: {
        default: "bg-ink text-paper hover:bg-ink-2",
        outline: "border-rule-strong bg-paper text-ink hover:bg-plate",
        secondary: "bg-plate text-ink hover:bg-rule",
        ghost: "text-ink hover:bg-plate",
        verified: "bg-verified text-paper hover:brightness-90",
        revision: "border-revision bg-paper text-revision hover:bg-revision-wash",
        link: "px-0 text-ink underline underline-offset-4 hover:text-ink-2",
      },
      size: {
        default: "min-h-11 px-4 md:min-h-10",
        sm: "min-h-11 px-3 text-[0.8125rem] md:min-h-8",
        lg: "min-h-12 px-5 text-base md:min-h-11",
        icon: "size-11 md:size-9",
        "icon-sm": "size-11 md:size-8",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  }
)

function Button({
  className,
  variant = "default",
  size = "default",
  ...props
}: ButtonPrimitive.Props & VariantProps<typeof buttonVariants>) {
  return (
    <ButtonPrimitive
      data-slot="button"
      className={cn(buttonVariants({ variant, size, className }))}
      {...props}
    />
  )
}

export { Button, buttonVariants }
