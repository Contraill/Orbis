const paths = {
  play: <path d="M7.5 5.2v13.6a.8.8 0 0 0 1.2.7l11-6.8a.8.8 0 0 0 0-1.4l-11-6.8a.8.8 0 0 0-1.2.7z" fill="currentColor" stroke="none" />,
  back: <path d="M15 5l-7 7 7 7" />,
  next: <path d="M9 5l7 7-7 7" />,
  down: <path d="M6 9l6 6 6-6" />,
  close: <path d="M6 6l12 12M18 6 6 18" />,
  check: <path d="M5 12.5l4.5 4.5L19 7.5" />,
  plus: <path d="M12 5v14M5 12h14" />,
  pause: <path d="M8 5v14M16 5v14" strokeWidth="3" />,
  rewind: <><path d="M4.5 12a7.5 7.5 0 1 0 2.2-5.3" /><path d="M4.5 4.5v3.8h3.8" /></>,
  forward: <><path d="M19.5 12a7.5 7.5 0 1 1-2.2-5.3" /><path d="M19.5 4.5v3.8h-3.8" /></>,
  expand: <path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5" />,
  shrink: <path d="M9 4v5H4M15 4v5h5M9 20v-5H4M15 20v-5h5" />,
  sound: <><path d="M4 9.5h3.5L12 5.5v13l-4.5-4H4z" /><path d="M16 9a4.2 4.2 0 0 1 0 6M18.6 6.5a7.8 7.8 0 0 1 0 11" /></>,
  muted: <><path d="M4 9.5h3.5L12 5.5v13l-4.5-4H4z" /><path d="M16.5 9.5l5 5M21.5 9.5l-5 5" /></>,
  search: <><circle cx="10.8" cy="10.8" r="6.6" /><path d="m16 16 4.5 4.5" /></>,
  together: <><circle cx="9" cy="8.5" r="3.2" /><circle cx="16.8" cy="9.5" r="2.5" /><path d="M3.5 19c.6-3 2.8-4.7 5.5-4.7s4.9 1.7 5.5 4.7M15 14.4c2.5-.5 4.7.8 5.5 3.9" /></>,
} as const;

export type IconName = keyof typeof paths;

export default function Icon({ name, size = 18 }: { name: IconName; size?: number }) {
  return <svg className="icon" viewBox="0 0 24 24" width={size} height={size} fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]}</svg>;
}
