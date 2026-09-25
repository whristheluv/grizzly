# GrizzlySMS Apple Turkey 자동 구매

사진의 Apple(`wx`), Turkey(`62`), 제공업체 `393,405,406,140` 설정을 사용합니다. 1분마다 재고를 확인해 GrizzlySMS 잔액으로 **번호 1개만** 구매하고 Discord 웹후크로 번호와 활성화 ID를 보냅니다. 카드 결제나 GrizzlySMS 잔액 충전은 하지 않습니다. `getNumber` 요청에는 `providerIds=393,405,406,140`, `maxPrice=1`이 적용됩니다. 구매 기록은 Cloudflare Durable Object에 보관합니다.

## 배포 준비

1. Cloudflare 계정과 Workers 접근 권한을 준비합니다.
2. `npm install` 후 `npx wrangler login`으로 로그인합니다.
3. `npx wrangler secret put GRIZZLY_API_KEY`, `npx wrangler secret put DISCORD_WEBHOOK_URL`로 각각 입력합니다. 구매 1건의 가격 상한은 `wrangler.jsonc`에 `$1`로 설정했습니다. 비밀값을 GitHub 코드에 쓰지 마세요. 기존 GitHub Actions secrets는 Cloudflare로 자동 이전되지 않습니다.
4. `npm run deploy`를 실행합니다. Cron은 UTC 기준 매분 실행됩니다. Cloudflare 화면에서 실제 실행 여부를 확인하세요.

## 동작 및 주의

- 선택한 제공업체 재고가 모두 0개면 구매하지 않습니다. 재고가 있으면 가격 상한을 적용해 `getNumber`를 한 번 호출합니다. `NO_NUMBERS`면 다음 실행에서 다시 확인합니다.
- 사진의 `THREADS=20`, `MAX_REQUESTS_PER_SECOND=5`, `REQUEST_TIMEOUT_SECONDS=10`, `STATUS_EVERY_REQUESTS=10`, `LOG_LEVEL=INFO`는 상시 실행 Docker 봇의 설정입니다. 이 프로젝트는 매분 한 번 실행되므로 해당 설정이 필요하지 않습니다.
- 성공 후에는 구매를 다시 시도하지 않으며, 알림이 실패한 경우에만 알림을 재시도합니다.
- 구매 API 요청의 결과가 불분명하거나 API 오류가 나면 중복 구매를 피하려고 멈추고 Discord로 확인 요청을 보냅니다. 이 경우 GrizzlySMS 활성화 목록을 확인해야 합니다.
- 이미 구매 기록이 있는 프로젝트를 재배포해도 구매 횟수는 초기화되지 않습니다. Durable Object 데이터를 삭제하거나 Worker 이름을 바꾸면 이 보장이 깨질 수 있습니다.
- 구매와 문자 수신, 계정 인증, 구독 요금 결제는 별개입니다. 이 코드는 SMS 수신이나 구독 결제를 자동화하지 않습니다.
- `npm test`로 구매 횟수 제한을 검증할 수 있습니다.
