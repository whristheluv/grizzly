import test from 'node:test';
import assert from 'node:assert/strict';
import { PurchaseCoordinator } from '../src/worker.js';

function harness({ stock = 1, purchase = 'ACCESS_NUMBER:123:905551234567', discordFails = false, maxPrice = '1' } = {}) {
  const data = new Map();
  const requests = [];
  const ctx = { storage: {
    get: async k => data.get(k), put: async (k, v) => { data.set(k, v); },
    delete: async k => { data.delete(k); },
  } };
  const env = { GRIZZLY_API_KEY: 'fake', DISCORD_WEBHOOK_URL: 'https://discord.com/api/webhooks/123/fake', MAX_PRICE: maxPrice, PROVIDER_IDS: '393,405,406,140' };
  const coordinator = new PurchaseCoordinator(ctx, env);
  const prior = globalThis.fetch;
  globalThis.fetch = async (url, options) => {
    const target = new URL(url);
    requests.push({ target, options });
    if (target.hostname === 'discord.com') return { ok: !discordFails };
    if (target.searchParams.get('action') === 'getPricesV3') return {
      ok: true, text: async () => JSON.stringify({ 62: { wx: { providers: { 393: { count: stock }, 405: { count: 0 }, 406: { count: 0 }, 140: { count: 0 } } } } }),
    };
    return { ok: true, text: async () => purchase };
  };
  return {
    coordinator, requests, data,
    tick: () => coordinator.fetch(new Request('https://internal/tick')),
    restore: () => { globalThis.fetch = prior; },
  };
}

test('no stock means no purchase', async () => {
  const h = harness({ stock: 0 });
  try {
    assert.equal((await h.tick()).status, 200);
    assert.equal(h.requests.filter(r => r.target.searchParams.get('action') === 'getNumber').length, 0);
  } finally { h.restore(); }
});

test('one purchase with provider and price cap, then no repeat', async () => {
  const h = harness();
  try {
    assert.equal((await h.tick()).status, 200);
    assert.equal((await h.tick()).status, 200);
    const buys = h.requests.filter(r => r.target.searchParams.get('action') === 'getNumber');
    assert.equal(buys.length, 1);
    assert.equal(buys[0].target.searchParams.get('providerIds'), '393,405,406,140');
    assert.equal(buys[0].target.searchParams.get('maxPrice'), '1');
    assert.equal(h.data.get('purchase-state').notified, true);
  } finally { h.restore(); }
});

test('unclear purchase outcome blocks automatic retry', async () => {
  const h = harness({ purchase: 'NO_BALANCE' });
  try {
    assert.equal((await h.tick()).status, 500);
    assert.equal((await h.tick()).status, 200);
    assert.equal(h.requests.filter(r => r.target.searchParams.get('action') === 'getNumber').length, 1);
    assert.equal(h.data.get('purchase-state').status, 'attempted');
    assert.equal(h.requests.filter(r => r.target.hostname === 'discord.com').length, 1);
  } finally { h.restore(); }
});

test('notification failure retries the message but never the purchase', async () => {
  const h = harness({ discordFails: true });
  try {
    assert.equal((await h.tick()).status, 500);
    assert.equal((await h.tick()).status, 500);
    assert.equal(h.requests.filter(r => r.target.searchParams.get('action') === 'getNumber').length, 1);
    assert.equal(h.requests.filter(r => r.target.hostname === 'discord.com').length, 2);
  } finally { h.restore(); }
});
