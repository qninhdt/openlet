import * as React from 'react';
import { cn } from '@/lib/utils';
import { controlStyles, focusStyles, invalidStyles } from './styles';

function Textarea({ className, ...props }: React.ComponentProps<'textarea'>) {
  return (
    <textarea
      data-slot="textarea"
      className={cn(
        controlStyles,
        focusStyles,
        invalidStyles,
        'flex field-sizing-content min-h-16 w-full px-3 py-2',
        className,
      )}
      {...props}
    />
  );
}

export { Textarea };
