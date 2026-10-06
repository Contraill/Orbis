/** Copy on HTTPS when available, with a synchronous fallback for HTTP/LAN browsers. */
export async function copyText(value: string): Promise<boolean> {
  if (navigator.clipboard?.writeText) {
    try { await navigator.clipboard.writeText(value); return true; }
    catch { /* The legacy selection path also works in non-secure contexts. */ }
  }
  const field = document.createElement("textarea");
  const focused = document.activeElement instanceof HTMLElement ? document.activeElement : null;
  field.value = value;
  field.readOnly = true;
  field.style.position = "fixed";
  field.style.left = "-9999px";
  document.body.appendChild(field);
  field.focus();
  field.select();
  let copied = false;
  try { copied = document.execCommand("copy"); }
  catch { copied = false; }
  field.remove();
  focused?.focus();
  return copied;
}
