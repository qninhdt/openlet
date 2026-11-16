import * as React from 'react';
import { cn } from '@/lib/utils';
import { controlStyles, focusStyles, invalidStyles } from './styles';

function Input({ className, type, ...props }: React.ComponentProps<'input'>) {
  return (
    <input
      type={type}
      data-slot="input"
      className={cn(
        controlStyles,
        focusStyles,
        invalidStyles,
        'h-8 w-full min-w-0 px-3 py-1 file:inline-flex file:h-6 file:border-0 file:bg-transparent file:text-sm file:font-medium file:text-foreground disabled:pointer-events-none',
        className,
      )}
      {...props}
    />
  );
}

export { Input };
