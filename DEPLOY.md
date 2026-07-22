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
| API 키 | GitHub Secrets / 서버 `.env` only |
| 헬스체크 | `GET /_stcore/health` |
| 다음 단계 | #3 상점·유료 전에 FastAPI 분리 검토 |

## 빠른 검증

```bash
curl -fsS http://127.0.0.1:8501/_stcore/health
docker compose ps
```
