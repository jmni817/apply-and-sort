"""사람인 기업정보에서 회사의 기업형태(대기업/중견기업/중소기업 등)를 찾는다.

외부 AI 는 인터넷에 접속하지 못하므로, 이 모듈이 사람인 공개 기업정보 페이지를 직접 조회해
그 결과를 AI 에게 넘긴다. (robots.txt 에서 허용된 /zf_user/company-info/ 페이지만 읽음)

- 회사 하나당 검색 페이지와 기업정보 페이지 몇 개만 읽고, 요청 사이에 잠깐 쉰다.
- 찾은 결과는 기업정보 탭에 저장되므로 같은 회사를 다시 조회하지 않는다.
- 조회에 실패해도 오류로 멈추지 않고 빈 결과를 돌려준다. (그때는 AI 지식만으로 판단)
"""

from __future__ import annotations

import logging
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Callable

log = logging.getLogger(__name__)

BASE_URL = "https://www.saramin.co.kr"
SEARCH_PATH = "/zf_user/search/company?searchword="
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) apply-and-sort (+https://github.com/jmni817/apply-and-sort)"
MAX_CANDIDATES = 6
PER_TERM = 3  # 검색어 하나에서 가져올 후보 수 (괄호를 뗀 이름의 결과가 밀려나지 않도록)
REQUEST_GAP_SECONDS = 0.4
# 'OO역점' 같은 지점·가맹점은 본사가 아니므로 후보에서 뺀다
_BRANCH_RE = re.compile(r"(점|지점|가맹점|대리점)\s*$|지점\b")

_LINK_RE = re.compile(r'href="(/zf_user/company-info/view\?csn=[^"&]+)')
_NAME_RE = re.compile(r'"legalName":"([^"]+)"')
# 예: "기업형태 : 중소기업, 업종 : 광고 대행업 |", "기업형태 : 대기업, 1000대기업, 업종 : 치킨 전문점 |"
_TYPE_RE = re.compile(r"기업형태 : ([^,\"]+),.*?업종 : ([^|\"]*)")
_CORP_MARKS_RE = re.compile(r"\(주\)|㈜|주식회사|\(유\)|유한회사|\(사\)|\s|[()\[\]·.,&-]")


@dataclass
class SaraminCompany:
    name: str  # 사람인에 등록된 회사명 (예: (주)가나다랩)
    company_type: str  # 기업형태 (대기업/중견기업/중소기업/기타/- 등)
    industry: str = ""
    url: str = ""


def normalize_name(name: str) -> str:
    """(주)·주식회사·공백·기호를 빼고 소문자로. '(주)가나다랩' == '가나다랩'"""
    return _CORP_MARKS_RE.sub("", name).lower()


def search_terms(company: str) -> list[str]:
    """검색어 후보: 원래 이름, 괄호를 뗀 이름, 괄호 안 이름. ('가나다 (라마바)' → 가나다, 라마바)"""
    terms = [company.strip()]
    outside = re.sub(r"\([^)]*\)", " ", company).strip()
    inside = re.findall(r"\(([^)]*)\)", company)
    for term in [outside, *inside]:
        term = " ".join(term.split())
        if term and term not in terms:
            terms.append(term)
    return terms


def parse_company_page(html: str, url: str = "") -> SaraminCompany | None:
    name = _NAME_RE.search(html)
    found = _TYPE_RE.search(html)
    if not (name and found):
        return None
    return SaraminCompany(name.group(1).strip(), found.group(1).strip(), found.group(2).strip(), url)


def _default_fetch(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=10) as response:
        return response.read().decode("utf-8", "replace")


class SaraminLookup:
    def __init__(
        self,
        *,
        fetch: Callable[[str], str] = _default_fetch,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self._fetch = fetch
        self._sleep = sleep

    def search(self, company: str) -> list[SaraminCompany]:
        """회사명으로 사람인 기업정보 후보를 찾는다. 실패하면 빈 목록."""
        links: list[str] = []
        try:
            for term in search_terms(company):
                html = self._fetch(BASE_URL + SEARCH_PATH + urllib.parse.quote(term))
                new = [link for link in dict.fromkeys(_LINK_RE.findall(html)) if link not in links]
                links.extend(new[:PER_TERM])
                self._sleep(REQUEST_GAP_SECONDS)
            results = []
            for link in links[:MAX_CANDIDATES]:
                info = parse_company_page(self._fetch(BASE_URL + link), BASE_URL + link)
                if info and not _BRANCH_RE.search(info.name):
                    results.append(info)
                self._sleep(REQUEST_GAP_SECONDS)
            return results
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            log.warning("사람인 조회 실패 (%s): %s", company, exc)
            return []


def exact_match(company: str, candidates: list[SaraminCompany]) -> SaraminCompany | None:
    """이름이 정확히 같은 후보. (주)·띄어쓰기·괄호 차이는 무시하고, 괄호 안 이름도 같은 회사로 본다."""
    wanted = {normalize_name(term) for term in search_terms(company)}
    for candidate in candidates:
        if normalize_name(candidate.name) in wanted:
            return candidate
    return None
