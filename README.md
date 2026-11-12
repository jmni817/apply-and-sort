<p align="center"><img src="assets/icon.svg" alt="apply-and-sort icon" width="160"></p>

<h1 align="center">🥝 apply-and-sort</h1>

<p align="center">
  <a href="https://github.com/jmni817/apply-and-sort/releases/latest"><img src="https://img.shields.io/github/downloads/jmni817/apply-and-sort/total?label=%EB%8B%A4%EC%9A%B4%EB%A1%9C%EB%93%9C&color=5fae4f" alt="총 다운로드 수"></a>
  <a href="https://github.com/jmni817/apply-and-sort/releases/latest"><img src="https://img.shields.io/github/v/release/jmni817/apply-and-sort?label=%EC%B5%9C%EC%8B%A0%20%EB%B2%84%EC%A0%84&color=2f8f5b" alt="최신 버전"></a>
  <a href="https://github.com/jmni817/apply-and-sort/actions/workflows/test.yml"><img src="https://github.com/jmni817/apply-and-sort/actions/workflows/test.yml/badge.svg" alt="테스트"></a>
</p>

<p align="center">
  <b>"키위 하나 먹는 동안, 흩어져 있던 취업준비 기록 정리 완료!"</b><br>
  A fresh & simple open-source dashboard that turns your job-application Google Sheet into pass-rate insights.
</p>

<p align="center">
  <a href="https://github.com/jmni817/apply-and-sort/releases/latest"><b>🥝 Windows용 exe 다운로드</b></a>
</p>

---

> 🌿 **시트의 기존 내용을 지우거나 덮어쓰지 않습니다.**
> 쓰는 곳은 비어 있는 '기업규모' 칸과, 회사 정보를 모아 두는 '기업정보' 탭뿐입니다.

> 🔑 **이 저장소와 exe에는 어떤 API 키·토큰도 들어 있지 않습니다.**
> 각자 본인의 Google 키(`credentials.json`)와 Claude API 키를 등록해서 본인 시트에 연결합니다.

<br>

## 🥝 목차

1. [무엇을 해주나요?](#-무엇을-해주나요)
2. [AI로 기업규모 칸 채우기](#-ai로-기업규모-칸-채우기-선택-기능)
3. [왜 만들었나요?](#-왜-만들었나요)
4. [시작하기 (Windows exe)](#-시작하기-windows-exe)
5. [Google Cloud 설정 (최초 1회)](#-google-cloud-설정-최초-1회)
6. [시트 형식](#-시트-형식)
7. [개발자용: Python으로 실행하기](#-개발자용-python으로-실행하기)
8. [보안 · 개인정보](#-보안--개인정보)
9. [프로젝트 구조 · 빌드](#-프로젝트-구조--빌드)

<br>

---

## 🥝 무엇을 해주나요?

구글 시트에 차곡차곡 쌓아 둔 지원 기록을 읽어서, **어디서 붙고 어디서 떨어지는지** 한 화면에 보여 줍니다.

### ① 한눈에 보는 숫자

맨 위에 **지원 수 · 서류 결과 나온 수 · 서류 합격 수 · 서류 합격률**이 크게 뜹니다.

### ② 기준별 서류 합격률

| 묶음 | 이런 질문에 답해요 |
|---|---|
| 지원형태별 | 간편지원이 일반지원보다 잘 붙을까? |
| 기업규모별 | 대기업은 정말 어려울까? |
| 기업규모별 · 인턴만 | 인턴만 보면 달라질까? |
| 고용형태별 | 정규직 vs 체험형 vs 전환형 |

결과가 아직 안 나온 지원은 합격률 계산에서 빼고 **'대기'** 로 따로 셉니다.

### ③ 시트는 평소처럼

새 지원은 늘 하던 대로 시트에 한 줄 적기만 하면 됩니다. 대시보드에서 **[새로고침]** 을 누르면 바로 반영돼요.

<br>

---

## 🌿 AI로 기업규모 칸 채우기 (선택 기능)

### 기업 규모는 직접 찾기 귀찮습니다

"대기업 위주로 쓸까, 중견도 넣을까?"를 판단하려면 지원한 회사마다 규모를 알아야 합니다.
그런데 40곳 넘는 회사를 하나하나 사람인에 검색하는 건 키위 열 개를 먹어도 안 끝나요.

### 회사명만 적어 두면 Claude가 찾아 채웁니다

**[기업규모 자동 채우기]** 를 누르면, 비어 있는 **'기업규모'** 칸을 Claude가 웹 검색으로 채웁니다.

- 사람인·잡코리아 기업정보, DART, 뉴스를 참고해 **대기업 / 중견기업 / 중소기업 / 알수없음** 중 하나로 분류해요.
- 이름이 같은 다른 회사와 헷갈리지 않도록 **지원 직무**도 함께 보고 확인해요.
- 찾은 결과는 **근거 한 문장**과 함께 '기업정보' 탭에 쌓여요. 같은 회사는 다시 검색하지 않아요.
- AI가 틀렸다면 '기업정보' 탭에서 고치면 됩니다. 다음부터는 **사람이 고친 값을 우선**해요.

### 보내는 정보와 한계

- Claude에게 보내는 건 **회사명과 지원 직무뿐**입니다. 합격 여부·비고는 보내지 않아요.
- 응답의 마지막 JSON(`size`, `industry`, `reason`)만 읽고, 형식이 틀리면 '알수없음'으로 둡니다.
- 기업 규모는 매출·계열 편입에 따라 바뀌고, 사람인 표기와 법적 분류가 다를 때도 있어요. 중요한 판단에는 '기업정보' 탭의 근거를 한 번 확인해 주세요.
- 새 회사 하나를 검색할 때 수십 원 정도의 API 비용이 듭니다. (모델 `claude-opus-5-5`, 회사당 웹 검색 최대 3번)

<br>

---

## 💚 왜 만들었나요?

취업 준비를 하면서 지원 기록을 구글 시트에 쌓았는데, "간편지원이 더 잘 붙나?", "대기업은 나한테 무리인가?" 같은 질문에 감으로만 답하고 있었습니다.

직접 세어 보니 생각과 달랐습니다.

- 정규직까지 섞어 보면 기업 규모별 서류 합격률은 25~32%로 비슷했습니다.
- 그런데 **인턴만 따로 보면 대기업 합격률이 가장 높았습니다.**
- 붙은 곳을 모아 보니 규모보다 **직무(플랫폼·IT 회사의 콘텐츠/AI 기획)** 가 더 큰 차이를 만들고 있었습니다.

이 분석을 매번 손으로 하지 않으려고 만든 도구입니다. 같은 시리즈인 [🍓 sip-and-sort](https://github.com/jmni817/sip-and-sort)가 메일함을 정리한다면, apply-and-sort는 **취준 기록**을 정리합니다.

<br>

---

## 🚀 시작하기 (Windows exe)

1. [Releases](https://github.com/jmni817/apply-and-sort/releases/latest)에서 `apply-and-sort.exe`를 받아 더블클릭합니다.
2. 대시보드 창이 열리면 **처음 설정** 4단계를 따라 합니다.
   1. Google OAuth 키(`credentials.json`) 등록 → [만드는 방법](#-google-cloud-설정-최초-1회)
   2. 구글 계정 연결 → **[Google 로그인 열기]** 를 눌러 로그인
   3. 구글 시트 주소와 탭 이름 저장
   4. Claude API 키 등록 (선택, [console.anthropic.com](https://console.anthropic.com)에서 발급)
3. 설정이 끝나면 바로 대시보드가 보입니다. 기업규모가 빈 행이 있으면 **[기업규모 자동 채우기]** 버튼이 나타나요.

설정과 키는 `%APPDATA%\apply-and-sort\` 폴더에 저장됩니다.

<br>

---

## 🔑 Google Cloud 설정 (최초 1회)

본인 시트에 접근하려면 본인 Google Cloud 프로젝트의 OAuth 키가 필요합니다.

1. [Google Cloud Console](https://console.cloud.google.com/)에서 새 프로젝트를 만듭니다. (이름 예: `apply-and-sort`)
2. **API 및 서비스 → 라이브러리**에서 **Google Sheets API**를 찾아 **사용**을 누릅니다.
3. **OAuth 동의 화면**을 설정합니다. 사용자 유형은 '외부'로 고르고, **테스트 사용자에 본인 Gmail을 추가**합니다.
4. **사용자 인증 정보 → 사용자 인증 정보 만들기 → OAuth 클라이언트 ID**를 누르고, 애플리케이션 유형을 **데스크톱 앱**으로 고릅니다.
5. 만든 클라이언트의 JSON을 내려받아 대시보드 1단계에서 등록합니다.

**로그인할 때 `403 오류: access_denied` (Google 인증 절차를 완료하지 않았습니다) 가 뜨면**
앱이 '테스트' 상태인데 로그인한 계정이 테스트 사용자 목록에 없어서 그렇습니다.
**Google 인증 플랫폼 → 대상(Audience) → 테스트 사용자 → Add users**에서 본인 Gmail을 추가한 뒤 다시 로그인하세요.
그다음 나오는 "확인되지 않은 앱" 경고는 **고급 → (앱 이름)(으)로 이동**을 누르면 됩니다.

> 요청하는 권한은 `spreadsheets` (내 구글 시트 읽기·쓰기) 하나뿐입니다. 드라이브의 다른 파일이나 Gmail에는 접근하지 않습니다.
> '테스트' 상태 앱은 구글 정책상 로그인이 7일마다 만료돼요. 그럴 땐 [구글 계정 연결]을 다시 눌러 주세요.

<br>

---

## 📄 시트 형식

1행이 헤더이고, 2행부터 지원 한 건이 한 줄입니다. 열 순서는 상관없고 **헤더 이름**으로 찾습니다.

| 지원형태 | 회사 | 직무 | 지원일 | 고용형태 | 서류 | … | 기업규모 |
|---|---|---|---|---|---|---|---|
| 간편 | 가나다랩 | 콘텐츠 마케터 | 26-11-01 | 전환형인턴 | 합격 | | 중소기업 |
| 일반 | 라마바전자 | 브랜드마케팅 | 26-10-20 | 정규직 | 불합격 | | |

- **꼭 필요한 열:** `회사`, `서류` (서류 칸은 `합격` / `불합격`, 그 외는 '대기'로 셈)
- **있으면 좋은 열:** `지원형태`, `직무`, `고용형태` (고용형태에 '인턴'이 들어가면 인턴으로 셈)
- **기업규모 열:** 없으면 맨 끝에 자동으로 만듭니다.
- 헤더 이름이 다르면 `config.yaml`의 `columns`에서 바꿀 수 있어요. ([예시](config.example.yaml))

<br>

---

## 🛠 개발자용: Python으로 실행하기

Python 3.11 이상이 필요합니다.

```bash
git clone https://github.com/jmni817/apply-and-sort.git
cd apply-and-sort
python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"
```

```bash
apply-and-sort                  # 대시보드 열기 (브라우저)
apply-and-sort summary          # 합격률 요약을 터미널에 출력
apply-and-sort classify         # 빈 기업규모 칸 채우기
pytest -q                       # 테스트
```

Claude API 키는 대시보드에서 등록하거나, 환경변수 `APPLY_AND_SORT_CLAUDE_API_KEY`로 넣을 수 있습니다.

<br>

---

## 🔒 보안 · 개인정보

- 대시보드는 이 PC(`127.0.0.1`)에서만 열리고, 실행할 때마다 새로 만든 접속 토큰이 있어야 쓸 수 있습니다.
- Google 토큰과 Claude 키는 설정 파일 옆의 파일에만 저장되며, 화면에는 등록 여부만 표시됩니다.
- `credentials.json`, `token.json`, `config.yaml`, `claude_api_key.txt`는 `.gitignore`에 들어 있어 커밋되지 않습니다.

<br>

---

## 🧩 프로젝트 구조 · 빌드

```
apply_and_sort/
  main.py           CLI 진입점 (dashboard / auth / summary / classify)
  server.py         로컬 대시보드 서버 (127.0.0.1 + 접속 토큰)
  sheets_client.py  Google Sheets API (OAuth, 읽기, 셀 쓰기, 재시도)
  records.py        시트 행 → 지원 기록
  stats.py          합격률 집계 (순수 함수)
  company.py        Claude 웹 검색 기업규모 분류
  tracker.py        읽기 → 분류 → 쓰기 흐름
  web/dashboard.html
tests/              pytest (시트·Claude 는 가짜 객체로 대체)
packaging/          PyInstaller 설정
```

**exe 빌드**

```bash
pip install -r requirements-build.txt
pyinstaller packaging/apply-and-sort.spec
```

`v`로 시작하는 태그를 push하면 GitHub Actions가 exe를 빌드해 Releases에 올립니다. 바뀐 내용은 [CHANGELOG](CHANGELOG.md)에 기록합니다.

<br>

---

<p align="center">MIT License · Made by <a href="https://github.com/jmni817">jmni817</a> · 같은 시리즈: <a href="https://github.com/jmni817/sip-and-sort">🍓 sip-and-sort</a></p>
