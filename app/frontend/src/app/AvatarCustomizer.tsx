import type { AvatarConfig } from "../types";
import { palette, traits } from "blobatar";
import ProfileAvatar, { expressions, shapes } from "./ProfileAvatar";
import { translate } from "./i18n";

const shapeNames: Record<keyof typeof shapes, string> = {
  round: "Round", organic: "Organic", boxy: "Boxy", capsule: "Capsule", nub: "Nub",
  cloud: "Cloud", droplet: "Droplet", hexagon: "Hexagon", sun: "Sun", triangle: "Triangle",
};
const expressionNames: Record<keyof typeof expressions, string> = {
  idle: "Calm", happy: "Happy", sad: "Sad", mad: "Angry", surprised: "Surprised",
  wink: "Wink", sleepy: "Sleepy", smug: "Confident", unsure: "Unsure", scared: "Scared",
  love: "Love", shy: "Shy", sick: "Sick", thinking: "Thinking",
};

function colorFor(hue: number, tone: AvatarConfig["tone"]) {
  const tones = { pale: .07, mid: .36, deep: .82, bright: .55 };
  return palette(hue, true, typeof tone === "number" ? tone : tone ? tones[tone] : .5).head ?? "#48b9bf";
}

const toneSamples = [.1, .28, .5, .7, .86, .97];
let colorSamples: { hue: number; tone: number; rgb: number[] }[] | null = null;
const rgb = (hex: string) => [1, 3, 5].map(index => parseInt(hex.slice(index, index + 2), 16));
function fromColor(value: string) {
  if (!colorSamples) colorSamples = toneSamples.flatMap(tone => Array.from({ length: 360 }, (_, hue) =>
    ({ hue, tone, rgb: rgb(colorFor(hue, tone)) })));
  const target = rgb(value);
  let best = colorSamples[0], distance = Infinity;
  for (const sample of colorSamples) {
    const score = sample.rgb.reduce((sum, channel, index) => sum + (channel - target[index]) ** 2, 0);
    if (score < distance) { best = sample; distance = score; }
  }
  return { hue: best.hue, tone: best.tone };
}

export default function AvatarCustomizer({ seed, config, locale, onChange, onRandomize, disabled = false }: {
  seed: string; config?: AvatarConfig | null; locale: "en-US" | "tr-TR";
  onChange: (config: AvatarConfig) => void; onRandomize: () => void; disabled?: boolean;
}) {
  const t = (key: string) => translate(locale, key);
  const current = config ?? {};
  const seeded = traits(seed);
  const visibleHue = current.hue ?? seeded.num("hue", 0, 360);
  const visibleTone = current.tone ?? seeded("tone");
  const groups = [
    { label: "Shape", field: "shape" as const, values: Object.keys(shapes), labels: shapeNames },
    { label: "Expression", field: "expression" as const, values: Object.keys(expressions), labels: expressionNames },
  ];
  return <div className="avatar-customizer">
    <div className="avatar-customizer-preview"><div className="avatar-preview-stage"><ProfileAvatar seed={seed} config={config} size={164} prominent /></div>
      <strong>{t("Your character")}</strong>
      <button type="button" className="quiet-action" disabled={disabled} onClick={onRandomize}>{t("Surprise me")}</button>
    </div>
    {groups.map(group => <fieldset key={group.field} className="avatar-option-group" disabled={disabled}>
      <legend>{t(group.label)}</legend>
      <div className="avatar-option-track">
        {group.values.map(value => {
          const selected = current[group.field] === value;
          const next = { ...current, [group.field]: value } as AvatarConfig;
          const label = t((group.labels as Record<string, string>)[value]);
          return <button key={value} type="button" className={`avatar-option ${selected ? "selected" : ""}`} aria-label={`${t(group.label)}: ${label}`} aria-pressed={selected} onClick={() => onChange(next)}>
            <ProfileAvatar seed={seed} config={next} size={48} staticPreview /><span>{label}</span>
          </button>;
        })}
      </div>
    </fieldset>)}
    <fieldset className="avatar-option-group" disabled={disabled}>
      <legend>{t("Color")}</legend>
      <div className="avatar-color-row">
        <label className="avatar-color-picker"><input type="color" value={colorFor(visibleHue, visibleTone)}
          aria-label={t("Choose avatar color")} disabled={disabled}
          onChange={event => onChange({ ...current, ...fromColor(event.target.value) })} />
          <span>{t("Choose avatar color")}</span></label>
      </div>
    </fieldset>
  </div>;
}
