export const API_BASE = window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1"
  ? `http://${window.location.hostname}:8000`
  : "http://localhost:8000";

async function requestWithXhr(url: string, options: RequestInit): Promise<{ ok: boolean; text: () => Promise<string>; json: () => Promise<any> }> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open(options.method || "GET", url, true);
    const headers = new Headers(options.headers);
    headers.forEach((value, key) => xhr.setRequestHeader(key, value));
    xhr.onload = () => {
      const body = xhr.responseText || "";
      resolve({
        ok: xhr.status >= 200 && xhr.status < 300,
        text: async () => body,
        json: async () => JSON.parse(body),
      });
    };
    xhr.onerror = () => reject(new Error("Network request failed"));
    xhr.send(options.body instanceof FormData ? options.body : (options.body as XMLHttpRequestBodyInit | null | undefined) ?? null);
  });
}

export async function fetchJson(path: string, options: RequestInit = {}): Promise<any> {
  const headers = new Headers(options.headers);
  if (!headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const requestOptions = {
    ...options,
    headers,
  };
  const response = typeof window.fetch === "function"
    ? await window.fetch(`${API_BASE}${path}`, requestOptions)
    : await requestWithXhr(`${API_BASE}${path}`, requestOptions);
  if (!response.ok) {
    let message = await response.text();
    try {
      const parsed = JSON.parse(message);
      message = typeof parsed.detail === "string" ? parsed.detail : JSON.stringify(parsed.detail, null, 2);
    } catch {
      // Keep the raw response text.
    }
    throw new Error(message);
  }
  return response.json();
}
