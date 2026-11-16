import type { ReactNode } from 'react';
import { ChevronRight } from 'lucide-react';
import { Button } from '@/components/ui/button';

export interface PageHeaderParent {
  title: string;
  onSelect: () => void;
}
/** Port of OpenBot PageHeader: the page owns identity/path and trailing controls; the frame owns navigation. */
export function PageHeader({
  title,
  identity,
  path,
  children,
}: {
  title: string;
  identity?: ReactNode;
  path?: readonly PageHeaderParent[];
  children?: ReactNode;
}) {
  return (
    <header className="page-header flex min-w-0 flex-1 items-center gap-2 pr-1 pl-3 max-[721px]:gap-0.5 max-[721px]:pl-0.5">
      <div className="page-header-identity flex min-w-0 flex-1 items-center gap-1">
        {identity ?? (
          <>
            {path?.map((parent, index) => (
              <span key={index} className="inline-flex min-w-0 items-center">
                <Button variant="ghost" size="xs" onClick={parent.onSelect}>
                  {parent.title}
                </Button>
                <ChevronRight className="size-3.5 shrink-0" />
              </span>
            ))}
            {title && <h1 className="truncate text-sm font-medium text-foreground">{title}</h1>}
          </>
        )}
      </div>
      <div className="page-header-actions flex shrink-0 items-center gap-1 max-[721px]:gap-0">
        {children}
      </div>
    </header>
  );
}
