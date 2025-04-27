/**
 * 인증 토큰을 자동으로 실어 보내는 fetch 헬퍼
 *  - opts.raw === true   →   그대로 res.json() 반환
 */
export async function fetchWithAuth<
  T extends Record<string, any> | void = any
>(
  url: string,
  opts: RequestInit & { raw?: boolean } = {},
): Promise<T> {
  const token   = localStorage.getItem("token");
  const headers = new Headers(opts.headers);

  headers.set("Authorization", `Bearer ${token}`);
  // body가 JSON이면 항상 Content‑Type 지정
  if (!opts.raw && (opts.body || !('body' in opts)))
    headers.set("Content-Type", "application/json");


  // ↓ raw 만 분리해서 fetch 에는 넘기지 않는다
  const { raw, ...fetchOpts } = opts;

  const res = await fetch(`http://localhost:8000${url}`, {
    ...fetchOpts,
    headers,
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}
