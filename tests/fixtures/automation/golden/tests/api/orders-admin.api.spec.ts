import { test, expect } from '@playwright/test';
import { apiUrl, at, jsonBody } from './support';

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

test("TC_ORD_005 Awkward names and an empty response", async ({ request }) => {
  // 1. POST /orders
  const response1 = await request.post(apiUrl("/orders"), {
    data: { ["__proto__"]: { "admin": true }, "key": process.env.API_KEY ?? '' },
  });
  expect(response1.status()).toBe(201);
  const body1 = await jsonBody(response1);
  const responseValue = at(body1, "id");
  const responseValue2 = at(body1, "ref");
  const bodyValue = at(body1, "status");
  const argumentsValue = at(body1, "a");
  const evalValue = at(body1, "b");
  // 2. POST /orders with the saved values
  const response2 = await request.post(apiUrl("/orders"), {
    data: { "ids": [responseValue2, bodyValue, argumentsValue, evalValue] },
  });
  expect(response2.status()).toBe(201);
  const body2 = await jsonBody(response2);
  const responseValue3 = at(body2, "id");
  // 3. DELETE /orders/{id} returns no body
  const response3 = await request.delete(apiUrl("/orders/" + String(responseValue3)));
  expect(response3.status()).toBe(204);
  const body3 = await jsonBody(response3);
  expect(at(body3, "error")).toBeUndefined();
});
