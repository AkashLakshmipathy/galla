// Handing a document to a customer.
//
// The device's own share sheet, deliberately — the owner taps Share and picks
// WhatsApp himself. Going through the WhatsApp Business API would mean Meta
// approval, SMS would mean DLT registration with TRAI, and email would mean
// production access on a mail service. All three are weeks of paperwork to
// replace a gesture the phone already does well.

export async function shareDocument({ path, title, text }) {
  if (!path) return false;
  const url = new URL(path, window.location.origin).href;
  try {
    if (navigator.share) {
      await navigator.share({ title, text: text ?? title, url });
      return true;
    }
    // `window.open` returns null when a popup blocker eats it, which is the
    // default on desktop for a click the browser did not consider trusted. We
    // used to return true anyway, so the owner — or a judge on a laptop —
    // tapped Share and got nothing at all: no window, no error, no clue. Same
    // tab always works, and a document he can see beats a tab he cannot.
    const opened = window.open(url, "_blank", "noopener");
    if (!opened) window.location.href = url;
    return true;
  } catch {
    // A dismissed share sheet rejects. The owner changed his mind; that is
    // not a failure and must not raise a toast at him.
    return false;
  }
}
