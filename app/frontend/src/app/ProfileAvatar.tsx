import Avatar from "boring-avatars";

const palette = ["#172c40", "#276a75", "#78bca8", "#eed9ac", "#c77e6c"];
export default function ProfileAvatar({ seed, size = 64 }: { seed: string; size?: number }) {
  return <Avatar name={seed} size={size} variant="beam" colors={palette} />;
}
