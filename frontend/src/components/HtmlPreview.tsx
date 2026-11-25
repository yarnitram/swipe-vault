/**
 * Isolated HTML preview for sanitized swipe HTML.
 *
 * Defense in depth on top of server-side sanitization:
 *  - rendered only inside <iframe sandbox=""> (no scripts, no same-origin, no forms, no top navigation)
 *  - a CSP meta tag is injected so remote images / tracking pixels / fonts / frames never load
 */
export const PREVIEW_CSP = "default-src 'none'; style-src 'unsafe-inline'; img-src data:";

function escapeAttr(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

export function buildPreviewSrcDoc(html: string): string {
  const csp = `<meta http-equiv="Content-Security-Policy" content="${escapeAttr(PREVIEW_CSP)}">`;
  const referrer = '<meta name="referrer" content="no-referrer">';
  const base =
    '<style>body{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;font-size:14px;line-height:1.5;color:#0f172a;margin:12px;word-wrap:break-word}img{max-width:100%}</style>';
  // The CSP meta must come first, before any content from the swipe.
  return `<!doctype html><html><head>${csp}${referrer}<meta charset="utf-8">${base}</head><body>${html}</body></html>`;
}

export default function HtmlPreview({ html, title = 'Sanitized HTML preview' }: { html: string; title?: string }) {
  return (
    <iframe
      title={title}
      sandbox=""
      referrerPolicy="no-referrer"
      srcDoc={buildPreviewSrcDoc(html)}
      className="h-96 w-full rounded-md border border-slate-200 bg-white"
    />
  );
}
