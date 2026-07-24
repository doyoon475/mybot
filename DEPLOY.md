# #8 배포 가이드 (단기 Streamlit)

상점·회원 고도화 전에는 **Streamlit 단일 앱**으로 배포합니다.  
이후 수익화 단계에서 FastAPI + 웹 프론트 분리를 검토합니다.

## 사전 준비

1. `cp .env.example .env` 후 API 키 입력
2. DB 동기화 (로컬/서버 공통)

```bash
pip install -r requirements.txt
python pull_db_release.py   # GitHub CLI(gh) 로그인 필요
```

3. 로컬 확인

```bash
streamlit run dashboard_v2.py
```

## A. Docker (AWS EC2 / Lightsail / 로컬)

```bash
# data_cache/quant_history.db 가 있는 상태에서
docker compose up --build -d
# http://<호스트>:8501
```

- `data_cache/` 볼륨으로 DB·`users.db`·포트 잠금 JSON이 유지됩니다.
- 보안 그룹/방화벽에서 **8501** 만 열고, 가능하면 리버스 프록시(Nginx) + HTTPS를 붙이세요.
- `.env`는 이미지에 넣지 말고 `env_file` / 호스트 환경변수로 주입하세요.

### 최소 EC2 체크리스트

- [ ] Ubuntu 22.04+, Docker + Compose 설치
- [ ] `git clone` → `.env` → `pull_db_release.py` → `docker compose up -d`
- [ ] 스왑/디스크: DB·캐시용 여유 공간(≥5GB 권장)
- [ ] 자동 재시작: compose `restart: unless-stopped` 적용됨
- [ ] 시크릿을 AMI/이미지에 bake하지 않기

## B. Streamlit Community Cloud

1. GitHub 리포 연결, 메인 파일: `dashboard_v2.py`
2. **Advanced settings → Secrets** 에 `.env` 내용을 TOML로 등록  
   예: `PERPLEXITY_API_KEY = "..."`  
3. 대용량 `quant_history.db`는 git에 없으므로:
   - Release에서 받아 persistent storage에 두거나
   - 배포 전 bootstrap 스크립트/수동 업로드가 필요합니다  
   (Cloud 무료 티어는 대용량 SQLite에 비적합 → **Docker/EC2 권장**)

## C. 운영 시 주의

| 항목 | 권장 |
|------|------|
| 회원 DB | `data_cache/users.db` 백업 |
| 퀀트 DB | Release `quant-db-latest` + 일일 Actions |
| DB 품질 | `db_quality_gate.py`: 빈 달 하한 + 직전월 급락 + (PER≥50% 또는 PBR≥80%) |
| API 키 | GitHub Secrets / 서버 `.env` only |
| 요약 메일 | Secrets: `SMTP_USER`, `SMTP_PASSWORD`(앱 비번), `NOTIFY_TO` |
| 헬스체크 | `GET /_stcore/health` |
| 다음 단계 | #3 상점·유료 전에 FastAPI 분리 검토 |

### 일일 요약 메일 설정 (Gmail)

1. Google 계정 → 보안 → **2단계 인증** 켜기 → **앱 비밀번호** 발급  
2. GitHub 리포 **Settings → Secrets and variables → Actions** 에 추가:
   - `SMTP_USER` = 발신 Gmail  
   - `SMTP_PASSWORD` = 앱 비밀번호  
   - `NOTIFY_TO` = 수신 주소 (예: 본인 Gmail)  
3. 평일 Actions 종료 시(성공/실패 모두) 커버리지·게이트·런 링크 요약이 옵니다.  
   DB 파일(~450MB)은 첨부하지 않습니다.

### DB가 다시 안 깨지게 (요약)
- **게이트:** 최신월 팩터가 빈약하면 Release 업로드 자체를 막음.
- **동시 쓰기 금지:** C9·ETL·pull 중에는 다른 writer/대시보드 적재를 끄기.
- **장기:** 적재 DB ≠ 서빙 DB 분리 (로드맵에 기록됨).

## 로컬 Docker 게이트 — BIOS 가상화 (삼성 노트북)

`#3 상점` 전 로컬에서 `docker compose` 검증하려면 **CPU 가상화(VT-x)** 가 BIOS에서 켜져 있어야 합니다.

### 현재 PC 진단 (2026-07-23)
| 항목 | 값 |
|------|-----|
| 기기 | SAMSUNG 960QHA · Intel Core Ultra 7 256V |
| BIOS 가상화 | **OK** (`HyperVisorPresent=True`) |
| WSL | **OK** (Ubuntu, VERSION 2) |
| Docker Desktop | **OK** — Engine Server 응답 (`docker version` Server 섹션 표시) |
| `docker compose up --build -d` | **OK (2026-07-23)** — `mybot-quant-lab-1` healthy · http://localhost:8501 |

로컬 검증:

```powershell
docker version
docker compose -f C:\mybot\docker-compose.yml ps
# (선택) docker compose -f C:\mybot\docker-compose.yml up --build -d
```

### BIOS에서 켜기 (사용자 작업 — 재부팅 필요)
1. 저장 작업 모두 저장 후 **재시작**.
2. 삼성 로고가 뜨면 **F2** (안 되면 **Fn+F2**) 연타.  
   또는 Windows: **설정 → 시스템 → 복구 → 고급 시작 → 지금 다시 시작 → 문제 해결 → 고급 옵션 → UEFI 펌웨어 설정**.
3. BIOS에서 아래 중 해당 항목을 **Enabled**:
   - `Intel Virtualization Technology` / `Intel VT-x`
   - (있으면) `Intel VT-d` / `Virtualization`
   - Advanced → CPU Configuration 쪽에 있는 경우가 많음
4. **Save & Exit** (보통 F10 → Yes).
5. Windows 부팅 후 확인:
   ```powershell
   Get-ComputerInfo | Select-Object HyperVisorPresent
   # True 이면 BIOS 가상화 OK
   ```

### WSL2 (Docker Engine용) — 완료됨
이미 Ubuntu(WSL2) + `docker-desktop` distro가 있으면 추가 설치 불필요.

신규 PC라면 관리자 PowerShell에서:

```powershell
wsl --install -d Ubuntu
# 필요 시 재부팅 후
& "$env:LocalAppData\Programs\DockerDesktop\Docker Desktop.exe"
docker version
```

## 빠른 검증

```bash
curl -fsS http://127.0.0.1:8501/_stcore/health
docker compose ps
```
