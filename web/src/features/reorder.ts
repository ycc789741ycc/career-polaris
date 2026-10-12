import type { KeyboardEvent } from "react";

/**
 * Moving things in a list by drag or by keyboard, for the Sections panel and
 * the lines on the résumé page: the same handle, the same keys.
 */

/** The list with the item at `from` moved to `to`, where it then sits.
 * Out of range, the list as it was. Pure. */
export function getMoved<T>(list: readonly T[], from: number, to: number): T[] {
  if (from === to || from < 0 || to < 0) return [...list];
  if (from >= list.length || to >= list.length) return [...list];
  const next = [...list];
  const [moved] = next.splice(from, 1);
  next.splice(to, 0, moved!);
  return next;
}

/** How far an arrow key moves a handle's item: up one, down one, or not a
 * move. Pure. */
export function getKeyStep(event: Pick<KeyboardEvent, "key">): -1 | 1 | null {
  if (event.key === "ArrowUp") return -1;
  if (event.key === "ArrowDown") return 1;
  return null;
}
