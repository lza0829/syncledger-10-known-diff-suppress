export async function getJSON(url) {
  const r = await fetch(url)
  if (!r.ok) throw new Error(await errorText(r))
  return r.json()
}

export async function postJSON(url, body = {}) {
  const r = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!r.ok) throw new Error(await errorText(r))
  return r.json()
}

async function errorText(r) {
  const text = await r.text()
  try {
    const parsed = JSON.parse(text)
    const detail = parsed.detail ?? parsed
    if (typeof detail === 'string') return detail
    if (detail?.message) return detail.message
  } catch {
    /* plain text body */
  }
  return text
}
