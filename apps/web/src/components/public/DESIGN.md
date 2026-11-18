---
name: Openlet public site
description: OpenBot’s dark public world with Openlet’s blue identity.
colors:
  brand: 'oklch(0.72 0.15 250)'
  brand-foreground: 'oklch(0.2 0.05 250)'
  background: 'oklch(0.243 0 0)'
  foreground: 'oklch(0.985 0 0)'
  card: 'oklch(0.265 0 0)'
  popover: 'oklch(0.285 0 0)'
  primary: 'oklch(0.95 0 0)'
  primary-foreground: 'oklch(0.2 0 0)'
  secondary: 'oklch(0.31 0 0)'
  muted: 'oklch(0.3 0 0)'
  muted-foreground: 'oklch(0.77 0 0)'
  accent: 'oklch(0.34 0 0)'
  border: 'oklch(1 0 0 / 10%)'
  input: 'oklch(1 0 0 / 16%)'
  sidebar: 'oklch(0.22 0 0)'
  storage-panel: '#67bd91'
  activity-panel: '#dbb665'
typography:
  display:
    fontFamily: 'Inter Variable, sans-serif'
    fontSize: 'clamp(3.5rem,6.5vw,6.75rem)'
    fontWeight: 500
    lineHeight: 0.96
    letterSpacing: '-0.055em'
  headline:
    fontFamily: 'Inter Variable, sans-serif'
    fontSize: 'clamp(2.5rem,4.5vw,4rem)'
    fontWeight: 500
    lineHeight: 1.05
    letterSpacing: '-0.045em'
  title:
    fontFamily: 'Inter Variable, sans-serif'
    fontSize: '1.5rem'
    fontWeight: 600
    lineHeight: 1.25
    letterSpacing: '-0.035em'
  body:
    fontFamily: 'Inter Variable, sans-serif'
    fontSize: '15px'
    lineHeight: '24px'
  label:
    fontFamily: 'Inter Variable, sans-serif'
    fontSize: '14px'
    fontWeight: 500
rounded:
  auth: '10px'
  inset: '18px'
  feature: '28px'
  pill: '9999px'
spacing:
  inline: '8px'
  action-gap: '12px'
  grid-gap: '16px'
  action-inline: '24px'
  card-mobile: '28px'
  card-desktop: '32px'
components:
  button-primary:
    backgroundColor: '{colors.primary}'
    textColor: '{colors.primary-foreground}'
    typography: '{typography.label}'
    rounded: '{rounded.pill}'
    height: '48px'
    padding: '0 24px'
  button-outline:
    backgroundColor: 'color-mix(in oklab, oklch(0.985 0 0) 5%, transparent)'
    textColor: '{colors.foreground}'
    typography: '{typography.label}'
    rounded: '{rounded.pill}'
    height: '48px'
    padding: '0 24px'
  button-sign-in:
    backgroundColor: '{colors.primary}'
    textColor: '{colors.primary-foreground}'
    typography: '{typography.label}'
    rounded: '{rounded.auth}'
    height: '48px'
    width: '100%'
  feature-card:
    backgroundColor: '{colors.card}'
    textColor: '{colors.foreground}'
    rounded: '{rounded.feature}'
---

# Design System: Openlet public site

## Overview

**Creative North Star: "OpenBot public site, Openlet identity"**

The public site ports OpenBot’s dark layouts and interactions with Openlet’s blue mark and existing Bloub agent avatars. Large Inter headings, broad spacing and soft-edged product demonstrations carry the page; charcoal surfaces keep the colorful agents legible. The source layout, rather than a newly invented aesthetic, is the visual authority.

This document applies only to PublicLayout and its public pages, including sign-in. It excludes the authenticated workspace and the AppShell rendered inside the app preview: those retain Geist and their independent theme. Sources are public-layout.tsx, landing-page.tsx, auth-page.tsx, public-motion.css and the .public-theme block in ../../globals.css; product commitments live in ../../../PRODUCT.md. The approved layout reference is nightly-labs/openbot at 6cf4e6df48b1ae3c0e9259e2b3abfc8a4799ea82 and the repository screenshot/ collection.

**Key Characteristics:**

- Dark public surfaces with blue Openlet identity.
- Inter typography with tight, large headings.
- Bloub avatars and real product UI supply the illustration.

## Colors

The palette is charcoal and near-white, with blue identity and purposeful colored product panels. Frontmatter values preserve the source OKLCH notation.

### Primary

- **Openlet blue** (`brand`): logo, selection, focused controls, active team index and workspace/member panels. It is not the default CTA fill.
- **Near-white action** (`primary`): primary CTA and Google sign-in fill; `primary-foreground` provides the dark label.

### Secondary

- **Storage green** and **Activity amber**: the corresponding stacked team panels only. Their labels use `brand-foreground`; do not turn these panels into a new general-purpose accent system.

### Neutral

- **Charcoal canvas** (`background`), **raised charcoal** (`card`) and **popover charcoal** (`popover`): public canvas, demonstrations and public menus.
- **Near-white ink** (`foreground`) and **quiet gray ink** (`muted-foreground`): headings versus supporting copy.
- **Secondary**, **muted** and **accent**: quiet surface and hover treatments. Translucent white borders separate adjacent surfaces; `sidebar` backs the preview frame.

**The Public Boundary Rule.** Scope the dark public palette to PublicLayout and public portal surfaces; keep the app’s appearance preference independent.

## Typography

**Display and Body Font:** Inter Variable, sans-serif. The public wrapper explicitly selects it; the application’s global sans font remains Geist.

The frontmatter hierarchy records the hero, section heading, feature title, feature copy and action label. Hero supporting copy uses a fluid size (`clamp(1rem,1.5vw,1.25rem)`) and relaxed leading (`1.55`), capped at the implemented width (`730px`). Navigation uses compact text (`13px`). Keep sentence case and the observed tight headline tracking.

## Layout

The shared centered container caps at (`1280px`) with horizontal padding of (`16px`), (`32px`) from the small breakpoint, and (`48px`) from the large breakpoint. The header is (`80px`) high. Desktop navigation appears at the large breakpoint; narrower screens use a sheet capped at (`min(90vw,380px)`).

The landing hero is centered, with its text block capped at (`880px`). Actions stack on narrow screens and become a row at the small breakpoint. Feature demonstrations use a single column before the large breakpoint, then an asymmetric twelve-column grid with the source spans. Team and question sections use paired columns at the large breakpoint. Preserve these source compositions when changing content.

Section spacing is broad and responsive: features use vertical padding of (`64px`) then (`96px`); teams use (`80px`) then (`128px`). Sign-in is a quiet, centered column capped at (`360px`) with no public header/footer. The preview is (`590px`) tall on narrow screens, (`620px`) from the small breakpoint, and uses (`16 / 10`) aspect ratio with maximum height (`760px`) at the large breakpoint.

## Elevation & Depth

Depth comes primarily from charcoal tonal steps, thin translucent borders, clipped product demonstrations and overlapping sticky team panels. Feature cards have no ambient shadow; hover strengthens their border. The closing avatar honeycomb uses a canvas-colored radial veil and a small blur to keep text readable. Public dropdowns inherit the existing menu shadow rather than introducing a separate landing-page shadow family.

## Shapes

Use pill silhouettes for public actions, badges and navigation. Feature and stacked team cards share broad corners (`28px`); inset demonstrations use smaller rounded rectangles. The Google sign-in button uses the inherited large radius recorded as `auth`. Borders remain thin; the decorative closing honeycomb clips avatars into hexagonal cells rather than replacing the avatars themselves.

## Components

### Buttons

Primary actions use near-white fill and dark text, not blue fill. The shared landing action is (`48px`) high with pill corners. Its secondary partner has a translucent foreground fill and border. Both reuse the house Button component, including color transitions, disabled opacity and a visible blue keyboard ring. Header actions are smaller (`36px`). Sign-in uses a full-width, softly rectangular Google action with pending and error states.

### Navigation and badges

The desktop navigation is a pill-shaped translucent enclosure with quiet labels; hover adds a subtle surface and brightens text. Mobile navigation uses the existing sheet. Provider badges are (`44px`) high pills arranged in opposing marquees.

### Cards and questions

Feature cards use the card tone, fine border, clipped demonstration and text padding from the spacing tokens. Titles are compact and bold; copy is muted. Team panels overlap while scrolling, scaling and darkening as the next card covers them. FAQ rows are line-separated accordion items with generous vertical padding and muted answers capped at (`60ch`). There is no standalone public text-input primitive to document; the embedded AppShell owns its controls.

### Brand, avatars and preview

Reuse the blue AppLogo and existing Bloub AgentAvatar assets. Preserve logo blinking, provider marquees and small demo animations, with reduced-motion rules. The real `/app-preview` AppShell runs automatically when visible and pauses when offscreen or the document is hidden. Keep loading feedback and the interactive iframe; do not turn it into a static screenshot or add playback controls. The public frame does not restyle the app inside it.

## Do's and Don'ts

### Do:

- Do port the approved OpenBot composition and interaction before adapting Openlet content.
- Do use the scoped public semantic palette and Inter on public pages.
- Do keep the AppShell preview real, interactive and automatically running while visible.
- Do preserve keyboard focus, reduced-motion behavior and sign-in loading/error states.

### Don't:

- Don’t apply this public system to the authenticated app or its Geist typography.
- Don’t replace Bloub avatars with plush characters or add a shader beam.
- Don’t add playback controls around the automatic AppShell preview.
- Don’t invent testimonials, prices or performance claims to fill the source layout.
