import { test, expect } from '@playwright/test';
import { apiUrl, at, jsonBody } from './support';

test("TC_ORD_001 Create an order and read it back", async ({ request }) => {
  // 1. POST /orders
  const response1 = await request.post(apiUrl("/orders"), {
    headers: { "Authorization": "Bearer " + (process.env.API_TOKEN ?? '') },
    data: { "lines": [{ "sku": "A-1", "quantity": 2 }], "note": "Say \"hi\" `now` ${not a placeholder}" },
  });
  expect(response1.status()).toBe(201);
  const body1 = await jsonBody(response1);
  expect(at(body1, "id")).toBeDefined();
  expect(at(body1, "status")).toEqual("pending");
  expect(at(body1, "lines[0].quantity")).toEqual(2);
  const orderId = at(body1, "id");
  expect(orderId, "id is missing from the response").toBeDefined();
  // 2. GET /orders/{id}
  const response2 = await request.get(apiUrl("/orders/" + String(orderId)), {
    headers: { "Authorization": "Bearer " + (process.env.API_TOKEN ?? '') },
    params: { "expand": "lines" },
  });
  expect(response2.status()).toBe(200);
  const body2 = await jsonBody(response2);
  expect(at(body2, "id")).toEqual(orderId);
  expect(String(at(body2, "lines[0].sku"))).toContain("A-");
  expect(at(body2, "error")).toBeUndefined();
});

test("TC_ORD_002 Reject an order without a token", async ({ request }) => {
  // 1. POST /orders without the Authorization header
  // TODO verify this request: the endpoint was not in the API description
  const response1 = await request.post(apiUrl("/orders"), {
    data: { "lines": [] },
  });
  expect(response1.status()).toBe(401);
  expect(await response1.text()).toContain("token");
});
