import { test, expect } from '@playwright/test';
import { apiUrl, at } from './support';

test.fixme("TC_ORD_003 Cancel an order", async ({ request }) => {
  // TODO: 1. DELETE /orders/{id}
  // TODO: 2. The customer receives a cancellation email
});

test("TC_ORD_004 Preflight and headers", async ({ request }) => {
  // 1. OPTIONS /orders
  const response1 = await request.fetch(apiUrl("/orders"), {
    method: "OPTIONS",
    headers: { "Origin": "https://shop.example" },
  });
  expect(response1.status()).toBe(204);
  // 2. HEAD /orders
  const response2 = await request.fetch(apiUrl("/orders"), {
    method: "HEAD",
    headers: { "X-Api-Key": (process.env.API_KEY ?? '') },
  });
  expect(response2.status()).toBe(200);
});
