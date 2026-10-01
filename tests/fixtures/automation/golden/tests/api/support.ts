// Helpers for the generated API tests.
import type { APIResponse } from '@playwright/test';

const API_BASE_URL = (process.env.API_BASE_URL ?? "https://api.demo-shop.test/v1").replace(/\/+$/, '');

export function apiUrl(path: string): string {
  return API_BASE_URL + path;
}

// The parsed JSON body, or undefined when the response has none (204, HEAD).
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export async function jsonBody(response: APIResponse): Promise<any> {
  const text = await response.text();
  return text ? JSON.parse(text) : undefined;
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
