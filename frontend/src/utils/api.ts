/**
 * 인증 토큰을 자동으로 실어 보내는 fetch 헬퍼
 *  - opts.raw === true → 그대로 res (Response) 또는 res.json() 반환
 */
export async function fetchWithAuth<T = any>(
  url: string,
  opts: RequestInit & { raw?: boolean } = {},
): Promise<T> {
  const token   = localStorage.getItem("token");
  const headers = new Headers(opts.headers);

  if (token) headers.set("Authorization", `Bearer ${token}`);

  // JSON Body면 Content-Type 지정
  if (opts.body && !(opts.body instanceof FormData))
    headers.set("Content-Type", headers.get("Content-Type") || "application/json");

  const { raw, ...fetchOpts } = opts;

  const res = await fetch(`http://localhost:8000${url}`, {
    redirect: "follow",     // 307 Redirect 도 따라가도록
    ...fetchOpts,
    headers,
  });

  // 성공 분기
  if (res.ok) return raw ? (await (opts.raw ? res : res.json())) as T
                         : (await res.json()) as T;

  /* ---------- 에러 처리 ---------- */
  let detail: any = {};
  try { detail = await res.json(); } catch { /* text/html 인 경우 무시 */ }

  // status·detail 을 가진 객체를 던진다
  const err = new Error(detail?.detail || res.statusText) as Error & { status:number; body:any };
  err.status = res.status;
  err.body   = detail;
  throw err;
}
