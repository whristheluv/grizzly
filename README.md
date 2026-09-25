# GrizzlySMS Apple / Turkey 자동 번호 구매

[ErwannCharlier/GrizzlySmsBot](https://github.com/ErwannCharlier/GrizzlySmsBot)을 바탕으로 Discord 알림과 번호 1개 구매 제한을 적용한 Docker 봇입니다. 사진의 설정을 그대로 사용하며, 요청하신 가격 상한만 **$1**로 설정했습니다.

| 설정 | 값 |
| --- | --- |
| SERVICE / COUNTRY | `wx` / `62` |
| MAX_PRICE | `1` |
| PROVIDER_IDS | `393,405,406,140` |
| THREADS | `20` |
| MAX_REQUESTS_PER_SECOND | `5` (모든 작업자 합계 상한) |
| REQUEST_TIMEOUT_SECONDS | `10` |
| STATUS_EVERY_REQUESTS | `10` |
| LOG_LEVEL | `INFO` |
| 알림 | Discord 웹후크 |

## 디스호스트에서 실행

GitHub에서 불러오기를 선택하고 Python, `main`, 이 저장소 URL로 봇을 생성합니다. Discord 봇 초대와 Intents 설정은 필요하지 않습니다. 이 프로그램은 Discord 웹후크만 사용합니다.

대시보드에서 `STARTUP_FILE`은 `bot.py`로 설정하고, 패키지가 자동 설치되지 않으면 `PY_PACKAGES`를 `requests==2.32.5 python-dotenv==1.1.1`로 지정합니다. 간편 설정의 환경변수에 `GRIZZLY_API_KEY`와 `DISCORD_WEBHOOK_URL`을 추가합니다. 다른 설정은 위 표의 값이 코드에 기본으로 적용됩니다. 따옴표는 필요하지 않습니다. **구매가 시작되므로 두 값과 가격 상한을 확인한 뒤 시작하세요.**

구매 기록인 `purchase.json`은 `bot.py`와 같은 프로젝트 폴더에 저장되도록 설정했습니다. 디스호스트 문서에 따르면 이 위치는 재시작 후에도 보존됩니다. 이 파일을 삭제하거나 다른 봇 인스턴스에서 동시에 실행하면 중복 구매할 수 있습니다.

## Docker에서 실행

Docker가 켜진 서버에서 저장소를 받은 뒤 `cp .env.example .env`로 복사합니다. `.env` 파일의 `GRIZZLY_API_KEY`와 `DISCORD_WEBHOOK_URL`만 본인 값으로 바꾸고 `docker compose up -d --build`를 실행합니다. 확인은 `docker compose logs -f --tail=100`, 중지는 `docker compose down`입니다. `.env`는 GitHub에 올리지 마세요. 기존 저장소의 GitHub Actions secrets는 새 저장소나 디스호스트로 자동 복사되지 않습니다.

봇은 실행 중 **계속** `getNumber`를 요청합니다. 요청 시작 속도는 전체 스레드를 합쳐 초당 최대 5회입니다. `NO_NUMBERS`이면 계속 찾고, 번호를 1개 확보하면 `purchase.json`(Docker에서는 `/data/purchase.json`)에 기록하고 구매를 멈춘 다음 Discord로 번호와 활성화 ID를 보냅니다.

요청 도중 네트워크 오류가 발생하면 구매 성공 여부가 불확실할 수 있어 자동 재요청을 멈춥니다. Discord 안내와 GrizzlySMS의 활성화 목록을 확인하세요. 기록용 Docker 볼륨을 지우거나 다른 서버에서 동시에 실행하면 중복 구매 방지가 깨질 수 있습니다.

GrizzlySMS의 **기존 잔액으로 번호를 구매**합니다. 카드 충전, 문자 수신, Apple 계정 인증, YouTube 구독 결제는 자동화하지 않습니다.
