export default function MediaCardSkeleton({ compact = false }: { compact?: boolean }) {
  return <div className={compact ? "media-skeleton compact" : "media-skeleton"} aria-hidden="true"><span className="media-skeleton-art" /><span className="media-skeleton-title" /><span className="media-skeleton-meta" /></div>;
}
