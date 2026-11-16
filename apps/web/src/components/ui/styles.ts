// OpenBot primitive geometry, using the app's shadcn theme in both color schemes.
export const transcriptStyles =
  'mx-auto w-full max-w-[clamp(1440px,65vw,1920px)] gap-3 px-3 pt-3 pb-6 sm:px-5';
export const focusStyles =
  'outline-none focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/50';
export const invalidStyles =
  'aria-invalid:border-destructive aria-invalid:ring-2 aria-invalid:ring-destructive/20';
export const controlStyles =
  'rounded-md border border-input bg-background text-sm text-foreground transition-colors placeholder:text-muted-foreground disabled:cursor-not-allowed disabled:opacity-50';
export const popupStyles = 'rounded-xl bg-popover text-popover-foreground shadow-menu outline-none';
export const popupMotionStyles =
  'duration-150 ease-out data-open:animate-in data-open:fade-in-0 data-open:zoom-in-95 data-closed:animate-out data-closed:fade-out-0 data-closed:zoom-out-95 motion-reduce:animate-none';
export const menuPanelStyles =
  'ui-action-menu z-50 w-max min-w-48 max-w-[min(288px,calc(100vw-16px))] overflow-x-hidden overflow-y-auto border-0 p-1.5';
export const menuItemStyles =
  'relative flex min-h-8 cursor-default items-center gap-2 rounded-lg px-2.5 py-1.5 text-sm leading-5 font-normal whitespace-nowrap outline-none select-none focus:bg-foreground/6 focus:text-popover-foreground data-highlighted:bg-foreground/6 data-highlighted:text-popover-foreground data-open:bg-foreground/6 data-open:text-popover-foreground data-inset:pl-8.5 data-disabled:pointer-events-none data-disabled:opacity-45 [&_svg]:pointer-events-none [&_svg]:size-4 [&_svg]:shrink-0 [&>svg]:stroke-[1.75] [&>svg]:text-muted-foreground focus:[&>svg]:text-popover-foreground data-highlighted:[&>svg]:text-popover-foreground data-open:[&>svg]:text-popover-foreground data-[variant=destructive]:text-destructive data-[variant=destructive]:[&>svg]:text-destructive data-[variant=destructive]:focus:bg-destructive/10 data-[variant=destructive]:focus:text-destructive data-[variant=destructive]:data-highlighted:bg-destructive/10 data-[variant=destructive]:data-highlighted:text-destructive';
export const menuLabelStyles =
  'px-2.5 py-1 text-xs font-medium text-muted-foreground data-inset:pl-8.5';
export const menuSeparatorStyles = '-mx-1.5 my-1.5 h-px bg-border';

export const dialogOverlayStyles =
  'fixed inset-0 z-50 bg-black/10 duration-150 supports-backdrop-filter:backdrop-blur-xs data-open:animate-in data-open:fade-in-0 data-closed:animate-out data-closed:fade-out-0 motion-reduce:animate-none';
export const dialogFrameStyles =
  'fixed top-1/2 left-1/2 z-50 grid w-full max-w-[calc(100%-2rem)] -translate-x-1/2 -translate-y-1/2 gap-4 p-4 text-sm';
export const dialogFooterStyles = 'flex flex-col-reverse gap-2 pt-2 sm:flex-row sm:justify-end';

export const fileReferenceStyles =
  'inline-flex max-w-full cursor-pointer items-center gap-1 align-middle text-inherit outline-none focus-visible:ring-2 focus-visible:ring-ring rounded-sm [&>svg]:size-4 [&>svg]:shrink-0 [&>svg]:text-current [&>span]:truncate [&>span]:underline [&>span]:decoration-current/50 [&>span]:underline-offset-3 hover:[&>span]:decoration-current';
