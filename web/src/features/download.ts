/**
 * Sends the browser to a signed download link. The link answers with
 * `Content-Disposition: attachment`, so the file is saved and the page stays
 * where it is (ADR 0038). Its own module so tests can stand in for it: jsdom
 * cannot navigate.
 */
export function startDownload(url: string): void {
  window.location.assign(url);
}
