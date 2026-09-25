# GrizzlySMS Apple / Turkey 문자 확인 및 최대 5개 번호 구매

[ErwannCharlier/GrizzlySmsBot](https://github.com/ErwannCharlier/GrizzlySmsBot)의 번호 검색 방식을 바탕으로 Discord 알림, 문자 확인, 최대 5개 구매 제한을 적용했습니다. 번호당 구매 가격 상한은 **$1**입니다.

| 설정 | 값 |
| --- | --- |
| SERVICE / COUNTRY | `wx` / `62` |
| MAX_PRICE | `1` |
| PROVIDER_IDS | `405` |
| 최대 구매 건수 | 기존에 산 번호를 포함해 `5`개 |
| 문자 대기 | 번호당 `60`초, 5초 간격으로 상태 확인 |
| THREADS | `20` |
| MAX_REQUESTS_PER_SECOND | `5` (모든 작업자 합계 상한) |
| REQUEST_TIMEOUT_SECONDS | `10` |
| STATUS_EVERY_REQUESTS | `10` |
| LOG_LEVEL | `INFO` |
| 알림 | Discord 웹후크 |

## 디스호스트에서 실행

GitHub에서 불러오기를 선택하고 Python, `main`, 이 저장소 URL로 봇을 생성합니다. Discord 봇 초대와 Intents 설정은 필요하지 않습니다. 이 프로그램은 Discord 웹후크만 사용합니다.

대시보드에서 `STARTUP_FILE`은 `bot.py`로 설정하고, 패키지가 자동 설치되지 않으면 `PY_PACKAGES`를 `requests==2.32.5 python-dotenv==1.1.1`로 지정합니다. 간편 설정의 환경변수에 `GRIZZLY_API_KEY`와 `DISCORD_WEBHOOK_URL`을 추가합니다. 다른 설정은 위 표의 값이 코드에 기본으로 적용됩니다. 따옴표는 필요하지 않습니다. **구매가 시작되므로 두 값과 가격 상한을 확인한 뒤 시작하세요.**

구매 기록인 `purchase.json`은 `bot.py`와 같은 프로젝트 폴더에 저장됩니다. 기존 기록의 구매 번호 1개를 총 5개에 포함합니다. 기존 기록에는 구매 시각이 없어 **새 버전 시작부터 1분간** 문자 상태를 확인합니다. 디스호스트 문서에 따르면 이 폴더는 재시작 후에도 보존됩니다. 파일을 삭제하거나 다른 봇 인스턴스에서 동시에 실행하면 누적 구매 제한이 깨질 수 있습니다.

## Docker에서 실행

Docker가 켜진 서버에서 저장소를 받은 뒤 `cp .env.example .env`로 복사합니다. `.env` 파일의 `GRIZZLY_API_KEY`와 `DISCORD_WEBHOOK_URL`만 본인 값으로 바꾸고 `docker compose up -d --build`를 실행합니다. 확인은 `docker compose logs -f --tail=100`, 중지는 `docker compose down`입니다. `.env`는 GitHub에 올리지 마세요. 기존 저장소의 GitHub Actions secrets는 새 저장소나 디스호스트로 자동 복사되지 않습니다.

봇은 **계속** `getNumber`를 요청합니다. 요청 시작 속도는 전체 스레드를 합쳐 초당 최대 5회입니다. `NO_NUMBERS`이면 계속 찾습니다. 번호를 받으면 Discord로 알리고, 5초마다 GrizzlySMS 문자 상태를 확인합니다. 1분 이내 문자가 오면 인증번호를 Discord로 보내고 종료합니다. 문자 없이 1분이 지나면 `setStatus=8`로 취소를 요청하며, **취소 확인 응답을 받은 경우에만** 다음 번호를 찾습니다. 총 5개를 사용하면 종료합니다. 각 구매와 결과는 `purchase.json`(Docker에서는 `/data/purchase.json`)에 보관합니다. 취소 시 환불 가능 여부는 GrizzlySMS의 실제 거래 내역을 확인하세요.

구매나 취소 요청 결과가 불명확하거나 문자 상태가 예상과 다르면 다음 번호 구매를 멈춥니다. Discord 안내와 GrizzlySMS의 활성화 목록을 확인하세요. 기록용 Docker 볼륨을 지우거나 다른 서버에서 동시에 실행하면 중복 구매 방지가 깨질 수 있습니다. 문자 인증을 실제 사이트에서 성공했는지는 봇이 알 수 없으므로, SMS가 오면 구매를 멈추고 이용자가 입력합니다.

GrizzlySMS의 **기존 잔액으로 번호를 구매**합니다. 카드 충전, Apple 계정 인증, YouTube 구독 결제는 자동화하지 않습니다.
