
export function isPublicHttpsUrl(value: string): boolean {
  try {
    const url = new URL(value);
    if (url.protocol !== "https:" || url.username || url.password) return false;
    const host = url.hostname.toLowerCase().replace(/\.$/, "").replace(/^\[|\]$/g, "");
    if (host === "localhost" || host === "localhost.localdomain" || host.endsWith(".localhost")) return false;
    if (/^\d+\.\d+\.\d+\.\d+$/.test(host)) {
      const [a, b] = host.split(".").map(Number);
      return !(a === 0 || a === 10 || a === 127 || a >= 224 ||
        (a === 100 && b >= 64 && b <= 127) || (a === 169 && b === 254) ||
        (a === 172 && b >= 16 && b <= 31) || (a === 192 && (b === 168 || b === 0 || b === 2)) ||
        (a === 198 && (b === 18 || b === 19 || b === 51)) || (a === 203 && b === 0));
    }
    // Allow only global unicast IPv6; reject mapped IPv4 and transition ranges.
    if (host.includes(":")) return /^[23]/.test(host) && !/^2001:(?:db8|0):/.test(host) && !host.startsWith("2002:");
    return host.includes(".") && !host.endsWith(".local") && !host.endsWith(".internal");
  } catch { return false; }
}

export function redactSecrets(value: string): string {
  return value.replace(/(\/key\/)[^/?#\s]+/gi, "$1***");
}

/** One deadline covers headers and streamed body; redirects are deliberately rejected. */
export async function readPublicText(url: string, maxBytes: number, timeoutMs = 30_000, headers: Record<string, string> = {}): Promise<string> {
  if (!isPublicHttpsUrl(url)) throw new Error("URL harus menggunakan HTTPS dan alamat publik.");
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  let reader: ReadableStreamDefaultReader<Uint8Array> | undefined;
  try {
    const response = await fetch(url, {
      redirect: "error", signal: controller.signal,
      headers: { Accept: "text/csv, application/json, text/html, text/plain", ...headers },
    });
    if (!response.ok) throw new Error(`Sumber mengembalikan HTTP ${response.status}.`);
    if (Number(response.headers.get("content-length")) > maxBytes) throw new Error("Respons melebihi batas ukuran.");
    reader = response.body?.getReader();
    if (!reader) return "";
    let size = 0;
    let text = "";
    const decoder = new TextDecoder("utf-8", { fatal: true });
    while (true) {
      const chunk = await reader.read();
      if (chunk.done) break;
      size += chunk.value.byteLength;
      if (size > maxBytes) throw new Error("Respons melebihi batas ukuran.");
      text += decoder.decode(chunk.value, { stream: true });
    }
    return text + decoder.decode();
  } catch {
    // Native fetch errors may include credential-bearing URLs.
    throw new Error("Gagal mengambil sumber: HTTP, batas ukuran, encoding, atau timeout.");
  } finally {
    if (reader) await reader.cancel().catch(() => {});
    controller.abort();
    clearTimeout(timer);
  }
}
