// Helpers for the generated API tests.
const API_BASE_URL = (process.env.API_BASE_URL ?? "https://api.demo-shop.test/v1").replace(/\/+$/, '');

export function apiUrl(path: string): string {
  return API_BASE_URL + path;
}

// Reads a path such as "data.items[0].id" from a parsed JSON body; undefined when it is missing.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function at(body: unknown, path: string): any {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  let current: any = body;
  for (const key of path.match(/[^.[\]]+/g) ?? []) {
    if (current === null || current === undefined) return undefined;
    current = current[key];
  }
  return current;
}
