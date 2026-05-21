// Simplified vector flags for the language switcher. Inline SVG renders
// identically across Windows, macOS and Linux — unlike unicode flag
// emoji (🇧🇷 / 🇺🇸) which fall back to letter codes on Windows.

import type { SVGProps } from "react";

/**
 * Brazilian flag — green field, yellow rhombus, blue celestial sphere.
 * Aspect ratio 7:10 (official), drawn here as 28×20 for crisp rendering
 * in a chip button without needing the white band + "Ordem e Progresso"
 * lettering (illegible at icon sizes anyway).
 */
export function BrazilFlag(props: SVGProps<SVGSVGElement>) {
  return (
    <svg
      viewBox="0 0 28 20"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden
      {...props}
    >
      <rect width="28" height="20" fill="#009C3B" />
      <polygon points="14,2.5 25.5,10 14,17.5 2.5,10" fill="#FFDF00" />
      <circle cx="14" cy="10" r="4.5" fill="#002776" />
    </svg>
  );
}

/**
 * Flag of the United States — 13 alternating red/white stripes and a
 * blue canton in the upper hoist. Stars are rendered as a 3×5 grid of
 * white dots so the canton reads as "stars" even at chip size.
 */
export function USFlag(props: SVGProps<SVGSVGElement>) {
  // Pre-computed Y positions of the 7 red stripes (1st, 3rd, ... 13th
  // stripes are red; each stripe is 20/13 ≈ 1.538 tall).
  const stripeH = 20 / 13;
  const redStripes = [0, 2, 4, 6, 8, 10, 12].map((i) => (
    <rect
      key={i}
      y={i * stripeH}
      width="28"
      height={stripeH}
      fill="#B22234"
    />
  ));
  // 3×5 grid of stars inside the canton; canton is 11×(7×stripeH).
  const cantonW = 11;
  const cantonH = stripeH * 7;
  const stars: JSX.Element[] = [];
  const cols = 5;
  const rows = 3;
  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      stars.push(
        <circle
          key={`${r}-${c}`}
          cx={((c + 0.5) * cantonW) / cols}
          cy={((r + 0.5) * cantonH) / rows}
          r="0.6"
          fill="#FFFFFF"
        />,
      );
    }
  }
  return (
    <svg
      viewBox="0 0 28 20"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden
      {...props}
    >
      <rect width="28" height="20" fill="#FFFFFF" />
      {redStripes}
      <rect width={cantonW} height={cantonH} fill="#3C3B6E" />
      {stars}
    </svg>
  );
}
