const API = 'https://api.grizzlysms.com/stubs/handler_api.php';
const KEY = 'purchase-state';

function maxPrice(value) {
  if (!/^(?:0|[1-9]\d*)(?:\.\d{1,2})?$/.test(String(value ?? '')) || Number(value) <= 0) {
    throw new Error('MAX_PRICE must be a positive amount with at most two decimals');
  }
  return String(value);
}

async function api(env, action, extra = {}) {
  const url = new URL(API);
  url.search = new URLSearchParams({ api_key: env.GRIZZLY_API_KEY, action, ...extra }).toString();
  const response = await fetch(url, { signal: AbortSignal.timeout(20_000) });
  if (!response.ok) throw new Error('Grizzly HTTP error');
  return (await response.text()).trim();
}

async function discord(env, content) {
  const url = new URL(env.DISCORD_WEBHOOK_URL);
  if (url.protocol !== 'https:' || url.hostname !== 'discord.com' ||
      !/^\/api\/webhooks\/\d+\/[^/]+$/.test(url.pathname)) throw new Error('Invalid Discord webhook');
  const response = await fetch(url, {
    method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ content, allowed_mentions: { parse: [] } }),
    signal: AbortSignal.timeout(20_000),
  });
  if (!response.ok) throw new Error('Discord HTTP error');
}

function stock(body) {
  const data = JSON.parse(body);
  if (!data?.['62']?.wx?.providers || typeof data['62'].wx.providers !== 'object') {
    throw new Error('Invalid Grizzly prices response');
  }
  const count = data?.['62']?.wx?.providers?.['405']?.count;
  if (count === undefined) return 0;
  if (!/^(?:0|[1-9]\d*)$/.test(String(count))) throw new Error('Invalid provider stock');
  return Number(count);
}

export class PurchaseCoordinator {
  constructor(ctx, env) {
    this.ctx = ctx;
    this.env = env;
    this.busy = false;
  }

  async fetch(request) {
    if (new URL(request.url).pathname !== '/tick') return new Response('Not found', { status: 404 });
    if (this.busy) return new Response('Busy');
    this.busy = true;
    try {
      await this.tick();
      return new Response('OK');
    } catch (error) {
      // API requests contain secrets. Never log request URLs or response bodies.
      console.error(`Check failed: ${error?.constructor?.name || 'Error'}`);
      return new Response('Check failed', { status: 500 });
    } finally {
      this.busy = false;
    }
  }

  async tick() {
    const env = this.env;
    if (!env.GRIZZLY_API_KEY || !env.DISCORD_WEBHOOK_URL) throw new Error('Missing secrets');
    const limit = maxPrice(env.MAX_PRICE);
    const state = await this.ctx.storage.get(KEY);
    if (state?.status === 'purchased') {
      if (!state.notified) {
        await discord(env, `✅ GrizzlySMS Apple / Turkey / provider 405 번호 구매 완료\n번호: ${state.phone}\n활성화 ID: ${state.id}`);
        await this.ctx.storage.put(KEY, { ...state, notified: true });
      }
      return;
    }
    // If the request outcome was unclear, stop: retrying could purchase again.
    if (state?.status === 'attempted') {
      if (!state.alerted) {
        await discord(env, '⚠️ GrizzlySMS provider 405 구매 결과를 확인할 수 없어 자동 구매를 중지했습니다. GrizzlySMS 활성화 목록을 확인해 주세요.');
        await this.ctx.storage.put(KEY, { ...state, alerted: true });
      }
      return;
    }

    const count = stock(await api(env, 'getPricesV3', { service: 'wx', country: '62' }));
    console.log(`Provider 405 stock: ${count}`);
    if (count === 0) return;

    // Persist the lock before any request that may charge the account.
    await this.ctx.storage.put(KEY, { status: 'attempted', at: new Date().toISOString() });
    const result = await api(env, 'getNumber', {
      service: 'wx', country: '62', providerIds: '405', maxPrice: limit,
    });
    if (result === 'NO_NUMBERS') {
      await this.ctx.storage.delete(KEY);
      return;
    }
    const match = /^ACCESS_NUMBER:(\d+):(\d+)$/.exec(result);
    if (!match) throw new Error('Purchase result needs manual review');
    const purchase = { status: 'purchased', id: match[1], phone: match[2], notified: false };
    await this.ctx.storage.put(KEY, purchase);
    await discord(env, `✅ GrizzlySMS Apple / Turkey / provider 405 번호 구매 완료\n번호: ${purchase.phone}\n활성화 ID: ${purchase.id}`);
    await this.ctx.storage.put(KEY, { ...purchase, notified: true });
  }
}

export default {
  async scheduled(_controller, env) {
    const stub = env.PURCHASE.getByName('apple-turkey-provider-405');
    const response = await stub.fetch('https://internal/tick');
    if (!response.ok) throw new Error('Grizzly check failed');
  },
};
