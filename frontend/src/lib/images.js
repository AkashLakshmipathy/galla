/* Shrinking a photo before it leaves the phone.
 *
 * A modern phone camera produces an 8000px, nine-megabyte image. Handwriting
 * and print are both perfectly legible at 1600px, and the difference is a
 * nine-megabyte upload over shop wifi versus a quarter-megabyte one — which is
 * most of the wait between pressing the shutter and seeing the result.
 *
 * Done on the phone rather than only on the server because the upload itself is
 * half the delay, and because a shop's connection is the slowest link in the
 * chain. The server shrinks again as a backstop for anything that arrives large.
 */

const MAX_EDGE = 1600;
const QUALITY = 0.82;
const SKIP_BELOW = 400 * 1024;

export async function shrinkForUpload(file) {
  if (!file?.type?.startsWith("image/") || file.size < SKIP_BELOW) return file;
  try {
    const bitmap = await createImageBitmap(file);
    const scale = Math.min(1, MAX_EDGE / Math.max(bitmap.width, bitmap.height));
    if (scale >= 1) {
      bitmap.close?.();
      return file;
    }
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(bitmap.width * scale);
    canvas.height = Math.round(bitmap.height * scale);
    const context = canvas.getContext("2d");
    context.imageSmoothingQuality = "high";
    context.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    bitmap.close?.();

    const blob = await new Promise((resolve) =>
      canvas.toBlob(resolve, "image/jpeg", QUALITY));
    if (!blob || blob.size >= file.size) return file;
    return new File([blob], file.name.replace(/\.[^.]+$/, "") + ".jpg",
                    { type: "image/jpeg", lastModified: Date.now() });
  } catch {
    // An older browser, a format canvas cannot decode, or memory pressure on a
    // big image. Sending the original is slower, not broken.
    return file;
  }
}
