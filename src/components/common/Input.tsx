import { InputHTMLAttributes, forwardRef } from 'react'
import { clsx } from 'clsx'

export interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  error?: boolean
}

export const Input = forwardRef<HTMLInputElement, InputProps>(
  ({ className, error, ...props }, ref) => {
    return (
      <input
        className={clsx(
          'w-full rounded-lg border px-3 py-2 text-sm',
          'bg-gray-50 dark:bg-gray-700',
          'border-gray-200 dark:border-gray-600',
          'focus:outline-none focus:ring-2 focus:ring-primary/50',
          'disabled:opacity-50 disabled:cursor-not-allowed',
          'placeholder:text-gray-400 dark:placeholder:text-gray-500',
          error && 'border-red-500 focus:ring-red-500/50',
          className
        )}
        ref={ref}
        {...props}
      />
    )
  }
)

Input.displayName = 'Input'
