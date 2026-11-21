// The orbit mark plus a typeset name; replaces the raster gradient wordmark in the UI.
export default function BrandMark({ className = "" }: { className?: string }) {
  return <span className={`brand-mark ${className}`} role="img" aria-label="Orbis">
    <img src="/brand/mark.png" alt="" /><span aria-hidden="true">ORBIS</span>
  </span>;
}
