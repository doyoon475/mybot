import os
import re
import time
import random
import shutil
from urllib.parse import urljoin, unquote, urlencode

import requests
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


DATA_EXTS = (".xlsx", ".xls", ".csv", ".zip")
API_BASE = "https://api.quantking.net/api/v1/user/"


def _list_data_files(folder):
    if not os.path.isdir(folder):
        return set()
    return {
        f for f in os.listdir(folder)
        if f.lower().endswith(DATA_EXTS) and not f.endswith(".crdownload")
    }


def _safe_filename(name: str) -> str:
    name = unquote(name).strip().replace("\n", " ")
    name = re.sub(r'[<>:"/\\|?*]', "_", name)
    return name[:180] if name else f"quant_{int(time.time())}.xlsx"


def _filename_from_url_or_cd(url: str, resp, fallback: str) -> str:
    cd = resp.headers.get("Content-Disposition", "") if resp is not None else ""
    m = re.search(r"filename\*=UTF-8''([^;]+)|filename=\"([^\"]+)\"|filename=([^;]+)", cd, re.I)
    if m:
        return _safe_filename(next(g for g in m.groups() if g))
    path = (url or "").split("?")[0].rstrip("/").split("/")[-1]
    if path and "." in path and len(path) < 120:
        return _safe_filename(path)
    base = re.sub(r"\s+", "", fallback)[:50] or f"quant_{int(time.time())}"
    return _safe_filename(f"{base}.xlsx")


def _get_auth_token(driver) -> str:
    for key in ("token", "accessToken", "access_token", "authToken"):
        try:
            val = driver.execute_script(f"return localStorage.getItem('{key}');")
            if val:
                return val
        except Exception:
            continue
    try:
        val = driver.execute_script(
            "return sessionStorage.getItem('token') || localStorage.getItem('token');"
        )
        if val:
            return val
    except Exception:
        pass
    return ""


def _api_session(token: str, user_agent: str) -> requests.Session:
    sess = requests.Session()
    sess.headers.update({
        "User-Agent": user_agent,
        "Content-Type": "application/json;charset=utf-8",
        "Accept": "application/json",
        "Origin": "https://quantking.net",
        "Referer": "https://quantking.net/",
    })
    # 사이트 axios 인터셉터가 넣는 형태(Bearer / raw) 둘 다 대비
    if token:
        if token.lower().startswith("bearer "):
            sess.headers["Authorization"] = token
        else:
            sess.headers["Authorization"] = f"Bearer {token}"
    return sess


def _api_get_json(sess: requests.Session, path: str, params=None):
    url = urljoin(API_BASE, path.lstrip("/"))
    resp = sess.get(url, params=params, timeout=60)
    if resp.status_code == 401 and "Bearer " in sess.headers.get("Authorization", ""):
        # Bearer 실패 시 raw token 재시도
        raw = sess.headers["Authorization"].replace("Bearer ", "", 1)
        sess.headers["Authorization"] = raw
        resp = sess.get(url, params=params, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    # 응답이 {data: ...} 래핑일 수 있음
    if isinstance(data, dict) and "data" in data and len(data) <= 3:
        return data["data"]
    return data


def _download_url(sess: requests.Session, url: str, download_dir: str, title: str):
    """
    Azure Blob에 QuantKing Bearer를 붙이면 403(잘못된 Authorization signature)이 난다.
    브라우저 window.open과 같이 Authorization 없이 GET한다.
    """
    headers = {
        "User-Agent": sess.headers.get("User-Agent", "Mozilla/5.0"),
        "Referer": "https://quantking.net/",
        "Accept": "*/*",
    }
    # 절대 Authorization / Content-Type(json) 을 Blob에 보내지 않음
    resp = requests.get(url, headers=headers, timeout=120, allow_redirects=True)
    resp.raise_for_status()
    ctype = (resp.headers.get("Content-Type") or "").lower()
    if "text/html" in ctype and b"<html" in resp.content[:500].lower():
        raise RuntimeError("첨부 대신 HTML 반환")

    fname = _filename_from_url_or_cd(url, resp, title)
    path = os.path.join(download_dir, fname)
    if os.path.exists(path) and os.path.getsize(path) > 1000:
        return fname, True

    with open(path, "wb") as f:
        f.write(resp.content)
    if os.path.getsize(path) < 500:
        os.remove(path)
        raise RuntimeError("저장 파일이 너무 작음")
    return fname, False


def _force_download_dir(driver, download_dir: str):
    abs_dir = os.path.abspath(download_dir)
    for cmd, args in (
        ("Page.setDownloadBehavior", {"behavior": "allow", "downloadPath": abs_dir}),
        ("Browser.setDownloadBehavior", {"behavior": "allow", "downloadPath": abs_dir}),
    ):
        try:
            driver.execute_cdp_cmd(cmd, args)
            return
        except Exception:
            continue


def _install_open_trap(driver):
    """React li onClick = window.open(fileUrl) → URL 가로채기."""
    driver.execute_script(
        """
        if (!window.__qk_trap_installed) {
            window.__qk_opens = [];
            window.__qk_orig_open = window.open.bind(window);
            window.open = function(url, name, specs) {
                try { window.__qk_opens.push(String(url || '')); } catch (e) {}
                return null;
            };
            window.__qk_trap_installed = true;
        } else {
            window.__qk_opens = [];
        }
        """
    )


def _pop_captured_urls(driver):
    try:
        urls = driver.execute_script(
            "var u = window.__qk_opens || []; window.__qk_opens = []; return u;"
        ) or []
        return [u for u in urls if u and u.startswith("http")]
    except Exception:
        return []


def _real_click(driver, element):
    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", element)
    time.sleep(0.15)
    try:
        ActionChains(driver).move_to_element(element).pause(0.1).click().perform()
        return
    except Exception:
        pass
    try:
        element.click()
    except Exception:
        driver.execute_script(
            """
            const el = arguments[0];
            ['pointerdown','mousedown','pointerup','mouseup','click'].forEach(t => {
                el.dispatchEvent(new MouseEvent(t, {bubbles:true, cancelable:true, view:window}));
            });
            """,
            element,
        )


def _wait_new_file(watch_dirs, before_maps, timeout=20):
    deadline = time.time() + timeout
    while time.time() < deadline:
        for d in watch_dirs:
            if not os.path.isdir(d):
                continue
            if any(f.endswith(".crdownload") for f in os.listdir(d)):
                time.sleep(0.4)
                continue
            now = _list_data_files(d)
            newf = now - before_maps.get(d, set())
            if newf:
                newest = max(
                    (os.path.join(d, f) for f in newf),
                    key=lambda p: os.path.getmtime(p),
                )
                if os.path.getsize(newest) > 500:
                    return newest
        time.sleep(0.4)
    return None


def _move_into_raw(src_path, download_dir):
    fname = os.path.basename(src_path)
    dest = os.path.join(download_dir, fname)
    if os.path.abspath(os.path.dirname(src_path)) == os.path.abspath(download_dir):
        return fname
    if os.path.exists(dest) and os.path.getsize(dest) > 1000:
        try:
            os.remove(src_path)
        except Exception:
            pass
        return fname
    shutil.move(src_path, dest)
    return fname


def _dump_debug_html(driver, page, idx):
    os.makedirs("debug_html", exist_ok=True)
    path = os.path.join("debug_html", f"page{page}_post{idx}.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(driver.page_source)
    print(f"         HTML 덤프: {os.path.abspath(path)}")


def _extract_post_no_from_url(url: str):
    m = re.search(r"/membership/detail/(\d+)", url or "")
    return m.group(1) if m else None


def run_quant_crawler(start_page=1, end_page=10):
    print("[퀀트 크롤러] 시작 — API fileList 직접수신 + window.open 폴백")

    download_dir = os.path.abspath("./quant_raw_data")
    os.makedirs(download_dir, exist_ok=True)
    downloads_fallback = os.path.abspath(os.path.join(os.path.expanduser("~"), "Downloads"))
    watch_dirs = [download_dir, downloads_fallback]
    print(f"저장 경로: {download_dir} | 현재 {len(_list_data_files(download_dir))}개")

    chrome_options = Options()
    prefs = {
        "download.default_directory": download_dir,
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "safebrowsing.enabled": True,
        "profile.default_content_settings.popups": 0,
    }
    chrome_options.add_experimental_option("prefs", prefs)
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option("useAutomationExtension", False)

    driver = webdriver.Chrome(options=chrome_options)
    _force_download_dir(driver, download_dir)

    ok_count = skip_count = fail_count = 0
    api_sess = None

    try:
        driver.get("https://quantking.net/membership/list?page=1")
        print("\n[수동 로그인] 60초 안에 로그인...")
        for i in range(60, 0, -10):
            print(f"  남은 시간: {i}초...")
            time.sleep(10)

        _force_download_dir(driver, download_dir)
        token = _get_auth_token(driver)
        ua = driver.execute_script("return navigator.userAgent;")
        if token:
            api_sess = _api_session(token, ua)
            print(f"API 토큰 확보됨 (len={len(token)}) — fileList 직접 다운로드 모드")
            # 사전 핑
            try:
                probe = _api_get_json(api_sess, "board/membership", {"page": 1, "limit": 1})
                items = probe.get("items") if isinstance(probe, dict) else None
                print(f"API 연결 OK | sample items={0 if items is None else len(items)}")
            except Exception as e:
                print(f"API 사전점검 실패 → UI 폴백 사용: {e}")
                api_sess = None
        else:
            print("localStorage 토큰 없음 → UI(window.open 가로채기) 폴백")

        print("\n자동 탐색 시작!")

        for page in range(start_page, end_page + 1):
            print(f"\n[페이지 {page}/{end_page}] 스캔 중...")

            # ---------- 1) API 우선 ----------
            if api_sess is not None:
                try:
                    listing = _api_get_json(
                        api_sess, "board/membership", {"page": page, "limit": 10}
                    )
                    items = listing.get("items") if isinstance(listing, dict) else listing
                    if not items:
                        print("  게시물 없음(API)")
                        continue
                    print(f"  {len(items)}개 처리(API)")

                    for idx, item in enumerate(items, 1):
                        try:
                            post_no = item.get("no") or item.get("id") or item.get("slug")
                            title = (item.get("title") or f"post_{post_no}")[:80]
                            # 제목 필터: 퀀트데이터만
                            compact = re.sub(r"\s+", "", title)
                            if "퀀트데이터" not in compact and "퀀트 데이터" not in title:
                                continue

                            detail = _api_get_json(api_sess, f"board/membership/{post_no}")
                            if not isinstance(detail, dict):
                                raise RuntimeError("detail 응답 형식 이상")
                            file_list = detail.get("fileList") or []
                            if not file_list:
                                fail_count += 1
                                print(f"  [실패][{page}] {idx} fileList 비어있음: {title[:28]}")
                                continue

                            saved_any = False
                            for furl in file_list:
                                if not isinstance(furl, str) or not furl.startswith("http"):
                                    continue
                                fname, already = _download_url(
                                    api_sess, furl, download_dir, title
                                )
                                if already:
                                    skip_count += 1
                                    print(f"  [스킵][{page}] {idx} 이미 있음: {fname[:50]}")
                                else:
                                    ok_count += 1
                                    print(
                                        f"  [성공-API][{page}] {idx}/{len(items)} → {fname[:50]} "
                                        f"| 총 {len(_list_data_files(download_dir))}개"
                                    )
                                saved_any = True
                            if not saved_any:
                                fail_count += 1
                                print(f"  [실패][{page}] {idx} 유효 file URL 없음: {title[:28]}")

                            time.sleep(random.uniform(0.6, 1.2))
                        except Exception as e:
                            fail_count += 1
                            print(f"  [에러-API][{page}] {idx}: {e}")
                            time.sleep(1.0)
                    continue  # 다음 페이지 (API 경로 성공 분기)
                except Exception as e:
                    print(f"  API 페이지 실패 → UI 폴백: {e}")

            # ---------- 2) UI 폴백: li 클릭 + window.open 가로채기 ----------
            page_url = f"https://quantking.net/membership/list?page={page}"
            driver.get(page_url)
            time.sleep(random.uniform(1.5, 2.5))
            _install_open_trap(driver)

            try:
                elements = driver.find_elements(
                    By.XPATH,
                    "//*[contains(text(), '퀀트데이터') or contains(text(), '퀀트 데이터')]",
                )
                post_texts = []
                for el in elements:
                    text = el.text.strip()
                    if text and len(text) > 10 and text not in post_texts:
                        post_texts.append(text)
            except Exception as e:
                print(f"  목록 파싱 에러: {e}")
                continue

            if not post_texts:
                print("  게시물 없음")
                continue
            print(f"  {len(post_texts)}개 처리(UI)")

            for idx, title_text in enumerate(post_texts, 1):
                try:
                    if idx > 1:
                        driver.get(page_url)
                        time.sleep(random.uniform(1.0, 1.8))
                        _install_open_trap(driver)

                    safe = title_text.replace("'", "").replace('"', "")
                    el = driver.find_element(By.XPATH, f"//*[contains(text(), '{safe}')]")
                    _real_click(driver, el)

                    try:
                        WebDriverWait(driver, 10).until(
                            EC.presence_of_element_located((By.CSS_SELECTOR, "section.file__box, .file__box"))
                        )
                    except Exception:
                        time.sleep(2.0)

                    time.sleep(0.5)
                    _install_open_trap(driver)

                    # 상세 API도 시도 (URL에 post no가 있으면)
                    post_no = _extract_post_no_from_url(driver.current_url)
                    if api_sess is not None and post_no:
                        try:
                            detail = _api_get_json(api_sess, f"board/membership/{post_no}")
                            for furl in (detail.get("fileList") or []):
                                fname, already = _download_url(
                                    api_sess, furl, download_dir, title_text
                                )
                                if already:
                                    skip_count += 1
                                    print(f"  [스킵][{page}] {idx} 이미 있음: {fname[:45]}")
                                else:
                                    ok_count += 1
                                    print(f"  [성공-API][{page}] {idx} → {fname[:45]}")
                                break
                            else:
                                raise RuntimeError("fileList 없음")
                            time.sleep(random.uniform(0.8, 1.5))
                            continue
                        except Exception as e:
                            print(f"         detail API 실패({e}) → 클릭 폴백")

                    lis = driver.find_elements(By.CSS_SELECTOR, "section.file__box li, .file__box li")
                    if not lis:
                        fail_count += 1
                        print(f"  [실패][{page}] {idx} file__box li 없음: {title_text[:28]}")
                        _dump_debug_html(driver, page, idx)
                        continue

                    saved = False
                    before_maps = {d: _list_data_files(d) for d in watch_dirs}
                    for li in lis:
                        _pop_captured_urls(driver)
                        _force_download_dir(driver, download_dir)
                        print(f"         li 클릭: {(li.text or '')[:40]}")
                        _real_click(driver, li)
                        time.sleep(0.8)

                        captured = _pop_captured_urls(driver)
                        if captured:
                            dl_sess = api_sess or requests.Session()
                            if api_sess is None:
                                for c in driver.get_cookies():
                                    dl_sess.cookies.set(c["name"], c["value"], domain=c.get("domain"))
                                dl_sess.headers["User-Agent"] = ua
                            for furl in captured:
                                try:
                                    fname, already = _download_url(
                                        dl_sess, furl, download_dir, title_text
                                    )
                                    if already:
                                        skip_count += 1
                                        print(f"  [스킵][{page}] {idx} 이미 있음: {fname[:45]}")
                                    else:
                                        ok_count += 1
                                        print(f"  [성공-trap][{page}] {idx} → {fname[:45]}")
                                    saved = True
                                    break
                                except Exception as e:
                                    print(f"         URL 저장 실패: {e}")
                            if saved:
                                break

                        new_path = _wait_new_file(watch_dirs, before_maps, timeout=12)
                        if new_path:
                            fname = _move_into_raw(new_path, download_dir)
                            ok_count += 1
                            print(f"  [성공-클릭][{page}] {idx} → {fname[:45]}")
                            saved = True
                            break

                    if not saved:
                        fail_count += 1
                        print(f"  [실패][{page}] {idx} 클릭/요청 모두 실패: {title_text[:28]}")
                        _dump_debug_html(driver, page, idx)

                    time.sleep(random.uniform(1.0, 2.0))
                except Exception as e:
                    fail_count += 1
                    print(f"  [에러][{page}] {idx}: {e}")

    except Exception as e:
        print(f"치명적 에러: {e}")
    finally:
        print(
            f"\n종료 | 성공 {ok_count} / 스킵 {skip_count} / 실패 {fail_count} | "
            f"폴더 {len(_list_data_files(download_dir))}개"
        )
        try:
            driver.quit()
        except Exception:
            pass


if __name__ == "__main__":
    run_quant_crawler(start_page=81, end_page=176)
