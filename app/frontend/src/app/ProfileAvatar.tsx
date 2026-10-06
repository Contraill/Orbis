import { Blobatar } from "@blobatar/react";
import { useGaze } from "@blobatar/react/gaze";
import { happy, idle, love, smug, surprised, thinking, wink, sad, mad, sleepy, unsure, scared, shy, sick } from "blobatar/expression";
import type { BlobatarOptions } from "blobatar";
import type { AvatarConfig } from "../types";
import "blobatar/motion.css";
import "blobatar/gaze.css";

// Stable shape bands from Blobatar v2.7's documented shape partition.
export const shapes = { round: .11, organic: .35, boxy: .55, capsule: .65, nub: .75, cloud: .825, droplet: .88, hexagon: .93, sun: .965, triangle: .99 } as const;
export const expressions = { idle, happy, sad, mad, surprised, wink, sleepy, smug, unsure, scared, love, shy, sick, thinking };
const tones = { pale: .07, mid: .36, deep: .82, bright: .55 };

function options(config?: AvatarConfig | null): BlobatarOptions {
  return {
    ...(config?.shape ? { traits: { shape: shapes[config.shape] } } : {}),
    ...(config?.expression ? { expression: expressions[config.expression] } : {}),
    ...(config?.hue != null ? { hue: config.hue } : {}),
    ...(config?.tone != null ? { tone: typeof config.tone === "number" ? config.tone : tones[config.tone] } : {}),
  };
}

type Props = { seed: string; config?: AvatarConfig | null; size?: number; prominent?: boolean; staticPreview?: boolean };

// The seed remains the identity; curated options only override supported traits.
export default function ProfileAvatar({ seed, config, size = 64, prominent = false, staticPreview = false }: Props) {
  if (staticPreview) return <Blobatar name={seed} size={size} {...options(config)} aria-hidden="true" />;
  return <Blobatar name={seed} size={size} animate={prominent ? "always" : "hover"} {...options(config)} aria-hidden="true" />;
}

export function GazingProfileAvatar({ seed, config, size = 64 }: Props) {
  const { ref } = useGaze({ travel: 5.5, lookAt: "pointer" });
  return <Blobatar ref={ref} name={seed} size={size} animate="always" {...options(config)} aria-hidden="true" />;
}
