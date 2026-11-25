# Orin control center design

## Product direction

Orin is a personal agent runtime. The control center should answer, in order:

1. What should Orin do next?
2. What is running, waiting, or needs my decision?
3. What did it do, and which services and models did it use?

The interface is a workbench, not a marketing page. Its first screen gives the
task composer the lead position, then shows recent work and decisions. Navigation
and system details remain available without competing with the current task.

## Visual rules

- Warm paper surfaces and graphite text provide a calm working area. Copper is
  reserved for actions and selection; green, amber, and red communicate states.
- Use IBM Plex Sans for reading and IBM Plex Mono for identifiers, timestamps,
  and counts. Keep a restrained type scale and tabular numbers.
- Use borders and spacing to distinguish surfaces. Reserve shadows for overlays.
- Use compact rows for repeatable records; cards are for a single decision or
  input. Do not turn every datum into a card.
- All state colors have a text label. Empty, loading, disconnected, and error
  states have a useful next step.
- Motion communicates navigation, focus, and feedback. Keep transitions short,
  animate opacity and transform, and honor `prefers-reduced-motion`.
- Preserve native form controls, visible focus rings, generous pointer targets,
  semantic headings, and keyboard operation.

## Layout

- Desktop: quiet left navigation rail; broad main work area; compact utility
  header. Workbench uses a primary column plus a narrow context column.
- Tablet and mobile: rail becomes a horizontally scrollable navigation strip;
  columns stack while task details and actions stay visible.
- Task history uses a list/detail layout. Approvals show exact parameters before
  actions. Schedules pair the creation form with the active job list.

## Research references

- [Linear's 2026 interface refresh](https://linear.app/now/behind-the-latest-design-refresh):
  keep dense information but reduce the weight of surrounding chrome.
- [Vercel Geist color system](https://vercel.com/geist/colors) and
  [typography](https://vercel.com/geist/typography): define roles for surfaces,
  borders, text, and tabular data rather than applying a brand color everywhere.
- [Carbon design resources](https://www.carbondesignsystem.com/getting-started/designing/design-resources)
  and [Atlassian Figma libraries](https://atlassian.design/get-started/design/figma-libraries/marketplace-partners/):
  references for reusable components and state variants; no design file is
  copied into Orin.
- [Atlassian motion guidance](https://atlassian.design/foundations/motion):
  motion should clarify changes and respect reduced-motion settings.
- [Vercel Web Interface Guidelines](https://vercel.com/design/guidelines) and
  [WCAG 2.2](https://www.w3.org/TR/WCAG22/): design complete states, visible
  focus, status labels, and sufficient text contrast.
