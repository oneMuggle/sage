import { cva, type VariantProps } from 'class-variance-authority';
import { clsx } from 'clsx';
import { ButtonHTMLAttributes, forwardRef } from 'react';

// Button 变体样式 — 对齐 DESIGN.md §7 设计 token 规范
// 主按钮：bg-ui-bg text-ui-foreground border-ui-border
// 次要按钮：bg-ui-surface text-ui-foreground
// 危险按钮：bg-error text-text-inverse (与 DESIGN.md §7 危险按钮的 bg-red-500 等价)
const buttonVariants = cva(
  'inline-flex items-center justify-center rounded-md font-medium transition-colors focus:outline-none focus:ring-2 focus:ring-primary/50 disabled:opacity-50 disabled:pointer-events-none',
  {
    variants: {
      variant: {
        primary: 'bg-ui-bg text-ui-foreground border border-ui-border hover:bg-ui-surface',
        secondary: 'bg-ui-surface text-ui-foreground hover:bg-ui-bg',
        ghost: 'hover:bg-ui-surface',
        danger: 'bg-error text-text-inverse hover:bg-error/90',
      },
      size: {
        sm: 'h-8 px-2 text-sm',
        md: 'h-10 px-4 text-sm',
        lg: 'h-12 px-6 text-base',
        icon: 'h-10 w-10',
      },
    },
    defaultVariants: {
      variant: 'primary',
      size: 'md',
    },
  },
);

export interface ButtonProps
  extends ButtonHTMLAttributes<HTMLButtonElement>, VariantProps<typeof buttonVariants> {
  children: React.ReactNode;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, children, ...props }, ref) => {
    return (
      <button className={clsx(buttonVariants({ variant, size, className }))} ref={ref} {...props}>
        {children}
      </button>
    );
  },
);

Button.displayName = 'Button';
