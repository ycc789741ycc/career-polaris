/**
 * The CareerPolaris mark: a path climbing from a dot (your evidence) to a
 * four-point star (the target role), on a rounded tile. The one source of the
 * icon's shapes; `web/public/icon.svg` is the same drawing at its default
 * colours, for the browser tab.
 */

export type AppIconVariant = "default" | "light" | "dark" | "green" | "outline";

const PATH = "M27 73 C 27 54, 50 62, 50 46 S 63 34, 66 31";
const STAR = "M74 13 L78 22 L87 26 L78 30 L74 39 L70 30 L61 26 L70 22 Z";

/** Tile, path and dot, star: the colour versions on the App icon board. */
export const APP_ICON_COLOURS: Record<
  AppIconVariant,
  { tile: string; line: string; star: string }
> = {
  default: { tile: "#c67139", line: "#f5ead8", star: "#ffe1d0" },
  light: { tile: "#f5ead8", line: "#c67139", star: "#8c491a" },
  dark: { tile: "#201e1d", line: "#f5ead8", star: "#c67139" },
  green: { tile: "#56633f", line: "#f5ead8", star: "#e1eecc" },
  // The route not taken yet: a dashed path to an empty star, on peach. The
  // Advisor shows it while no target is set.
  outline: { tile: "#ffe1d0", line: "#c67139", star: "#c67139" },
};

export function AppIcon({
  size = 28,
  variant = "default",
  label,
}: {
  size?: number;
  variant?: AppIconVariant;
  /** Names the icon for assistive technology; without one it is decorative. */
  label?: string;
}) {
  const colours = APP_ICON_COLOURS[variant];
  const isOutline = variant === "outline";
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 100 100"
      data-variant={variant}
      {...(label
        ? { role: "img", "aria-label": label }
        : { "aria-hidden": true })}
      style={{ flex: "0 0 auto" }}
    >
      <rect width="100" height="100" rx="24" fill={colours.tile} />
      <path
        d={PATH}
        fill="none"
        stroke={colours.line}
        strokeWidth="7"
        strokeLinecap="round"
        strokeDasharray={isOutline ? "2 12" : undefined}
      />
      <circle cx="27" cy="73" r="7.5" fill={colours.line} />
      {isOutline ? (
        <path
          d={STAR}
          fill="none"
          stroke={colours.star}
          strokeWidth="3"
          strokeLinejoin="round"
        />
      ) : (
        <path d={STAR} fill={colours.star} />
      )}
    </svg>
  );
}
