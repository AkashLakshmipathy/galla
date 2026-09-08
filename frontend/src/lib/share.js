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
    window.open(url, "_blank", "noopener");
    return true;
  } catch {
    // A dismissed share sheet rejects. The owner changed his mind; that is
    // not a failure and must not raise a toast at him.
    return false;
  }
}
