# -*- coding: utf-8 -*-
# //@name:Hanime1
# //@id:hanime1
# //@version:6
# //wab201 学习研究用

import base64
import importlib
import json
import os
import re
import threading
import time
from http.cookies import SimpleCookie
from urllib.parse import parse_qs, urljoin, urlsplit

import requests
from lxml import html

try:
    cloudscraper = importlib.import_module("cloudscraper")
except Exception as exc:  # optional dependency; requests remains the fallback
    cloudscraper = None
    CLOUDSCRAPER_IMPORT_ERROR = "%s: %s" % (type(exc).__name__, exc)
else:
    CLOUDSCRAPER_IMPORT_ERROR = ""

from base.spider import Spider


class CFBlockedError(RuntimeError):
    pass


class DomainRedirectError(RuntimeError):
    pass


class HostContentError(RuntimeError):
    def __init__(self, kind, message):
        super().__init__(message)
        self.kind = kind


class Spider(Spider):
    HOST = "https://hanime1.com"
    DEFAULT_HOSTS = (
        "https://hanime1.com",
        "https://hanime1.me",
    )
    REGION_HOSTS = {
        "jp": "https://hanime1.com",
        "japan": "https://hanime1.com",
        "日本": "https://hanime1.com",
        "other": "https://hanime1.com",
        "global": "https://hanime1.com",
        "其他": "https://hanime1.com",
    }
    PLAY_PREFIX = "hanime1://play/"
    CATEGORIES = (
        ("all", "全部", ""),
        ("hentai", "裏番", "裏番"),
        ("short", "泡麵番", "泡麵番"),
        ("motion", "Motion Anime", "Motion Anime"),
        ("cg3d", "3DCG", "3DCG"),
        ("d25", "2.5D", "2.5D"),
        ("d2", "2D動畫", "2D動畫"),
        ("ai", "AI生成", "AI生成"),
        ("mmd", "MMD", "MMD"),
        ("cosplay", "Cosplay", "Cosplay"),
    )
    SORTS = (
        "最新上市",
        "最新上傳",
        "本日排行",
        "本週排行",
        "本月排行",
        "觀看次數",
        "讚好比例",
        "時長最長",
        "他們在看",
    )
    DURATIONS = (
        "",
        "1 分鐘 +",
        "5 分鐘 +",
        "10 分鐘 +",
        "20 分鐘 +",
        "30 分鐘 +",
        "60 分鐘 +",
        "0 - 10 分鐘",
        "0 - 20 分鐘",
    )
    VIDEO_RE = re.compile(r"\.(?:mp4|m3u8|mkv|webm)(?:$|[?#])", re.I)
    MEDIA_HOSTS = ("vdownload.hembed.com",)

    def __init__(self):
        self.name = "Hanime1"
        self.host = self.HOST
        self.timeout = 20
        self.retries = 2
        self.preferred_quality = 0
        self.trust_env = True
        self.cookie = ""
        self.cookie_by_host = {}
        self.media_cookie_by_host = {}
        self.host_candidates = list(self.DEFAULT_HOSTS)
        self.media_hosts = set(self.MEDIA_HOSTS)
        self.last_host_failures = []
        self.allow_domain_redirect = False
        self.forward_site_cookie_to_player = True
        self.cookie_cache = True
        self.cookie_cache_path = ""
        self.cookie_writeback_interval = 300
        self._cookie_cache_status = "idle"
        self._cookie_cache_signature = ""
        self._cookie_cache_saved_at = 0.0
        self._cookie_lock = threading.Lock()
        self.user_agent = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/138.0.0.0 Safari/537.36"
        )
        self.backend_parse = False
        self.category_mode = False
        self.categoryMode = False
        self.session = None
        self.use_cloudscraper = True
        self.session_backend = "uninitialized"
        self.session_backend_error = ""

    def getName(self):
        return self.name

    def init(self, extend=""):
        config = self._config(extend)
        self.host_candidates = self._configured_hosts(config)
        self.host = self.host_candidates[0]
        self.timeout = self._bounded_int(config.get("timeout"), 20, 8, 45)
        self.retries = self._bounded_int(config.get("retries"), 2, 0, 4)
        self.preferred_quality = self._bounded_int(
            config.get("preferred_quality"), 0, 0, 4320
        )
        self.trust_env = self._bool(config.get("trust_env"), True)
        self.use_cloudscraper = self._bool(
            config.get("use_cloudscraper"), True
        )
        self.cookie_cache = self._bool(config.get("cookie_cache"), True)
        self.cookie_writeback_interval = self._bounded_int(
            config.get("cookie_writeback_interval"), 300, 30, 86400
        )
        configured_cache_path = str(config.get("cookie_cache_path") or "").strip()
        self.cookie_cache_path = configured_cache_path or self._default_cookie_cache_path()
        if self._bool(config.get("clear_cookie_cache"), False):
            self._clear_cookie_cache()
        cached = self._load_cookie_cache()
        self.cookie = str(
            config.get("cookie") or config.get("cf_cookie") or ""
        ).strip()
        self.cookie_by_host = self._cookie_map(cached.get("cookies"))
        self.cookie_by_host.update(self._cookie_map(
            config.get("cookie_by_host") or config.get("cookies")
        ))
        if self.cookie:
            self.cookie_by_host.setdefault(self._hostname(self.host), self.cookie)
        self.media_cookie_by_host = self._cookie_map(
            config.get("media_cookie_by_host") or config.get("media_cookies")
        )
        self.media_hosts = self._configured_media_hosts(config)
        self.allow_domain_redirect = self._bool(
            config.get("allow_domain_redirect"), False
        )
        self.forward_site_cookie_to_player = self._bool(
            config.get("forward_site_cookie_to_player"), True
        )
        self.user_agent = str(
            config.get("user_agent") or cached.get("user_agent") or self.user_agent
        ).strip()
        self._reset_session()
        if self.cookie_by_host:
            self._save_cookie_cache(force=bool(self.cookie or config.get("cookie_by_host") or config.get("cookies")))

    def destroy(self):
        if self.session is not None:
            try:
                self.session.close()
            except Exception:
                pass
        self.session = None

    def isVideoFormat(self, url):
        return bool(self.VIDEO_RE.search(str(url or "")))

    def manualVideoCheck(self):
        return False

    def localProxy(self, params):
        return [404, "text/plain; charset=utf-8", b""]

    def homeContent(self, filter):
        classes = [
            {"type_id": type_id, "type_name": type_name}
            for type_id, type_name, _ in self.CATEGORIES
        ]
        filters = {}
        sort_values = [{"n": value, "v": value} for value in self.SORTS]
        duration_values = [
            {"n": value or "全部", "v": value} for value in self.DURATIONS
        ]
        for type_id, _, _ in self.CATEGORIES:
            filters[type_id] = [
                {"key": "sort", "name": "排序", "value": sort_values},
                {"key": "duration", "name": "時長", "value": duration_values},
            ]
        return {"class": classes, "filters": filters}

    def homeVideoContent(self):
        result = self.categoryContent("all", "1", False, {"sort": "最新上傳"})
        return {"list": result.get("list", [])}

    def categoryContent(self, tid, pg, filter, extend):
        page = self._page(pg)
        genre = self._category_genre(tid)
        options = self._config(extend)
        params = {
            "sort": str(options.get("sort") or "最新上傳"),
            "page": page,
        }
        duration = str(options.get("duration") or "").strip()
        if genre:
            params["genre"] = genre
        if duration:
            params["duration"] = duration
        try:
            source, page_url = self._request_text(
                "/search", params=params, expected="listing"
            )
            return self._parse_listing(source, page, page_url)
        except Exception as exc:
            return self._empty_page(page, "分類讀取失敗: %s" % exc)

    def searchContent(self, key, quick, pg="1"):
        page = self._page(pg)
        keyword = self._clean(key)
        if not keyword:
            return self._empty_page(page)
        try:
            source, page_url = self._request_text(
                "/search",
                params={"query": keyword, "page": page},
                expected="search",
            )
            return self._parse_listing(source, page, page_url)
        except Exception as exc:
            return self._empty_page(page, "搜尋失敗: %s" % exc)

    def detailContent(self, ids):
        raw_id = ids[0] if isinstance(ids, (list, tuple)) and ids else ids
        video_id = self._video_id(raw_id)
        if not video_id:
            return {"list": []}
        try:
            source, page_url = self._request_text(
                "/watch", params={"v": video_id}, expected="detail"
            )
            return {"list": [self._parse_detail(source, video_id, page_url)]}
        except Exception as exc:
            message = "詳情讀取失敗: %s" % exc
            return {
                "list": [
                    {
                        "vod_id": video_id,
                        "vod_name": "Hanime1 %s" % video_id,
                        "vod_remarks": message,
                        "vod_content": message,
                        "vod_play_from": "Hanime1直鏈",
                        "vod_play_url": "重試$%s%s/0" % (self.PLAY_PREFIX, video_id),
                    }
                ]
            }

    def playerContent(self, flag, id, vipFlags):
        video_id, requested_quality = self._play_id(id)
        if not video_id:
            return self._player_error("無法識別播放 ID")
        try:
            source, page_url = self._request_text(
                "/watch", params={"v": video_id}, expected="media"
            )
            sources = self._parse_sources(self._document(source), page_url)
            selected = self._select_source(sources, requested_quality)
            if not selected:
                return self._player_error("播放頁沒有可用的直鏈")
            return {
                "parse": 0,
                "jx": 0,
                "playUrl": "",
                "url": selected[1],
                "header": self._playback_headers(selected[1], page_url),
            }
        except Exception as exc:
            return self._player_error("播放解析失敗: %s" % exc)

    def _reset_session(self):
        self.destroy()
        self.session = self._create_session()
        self.session.trust_env = self.trust_env
        self.session.headers.update(
            {
                "User-Agent": self.user_agent,
                "Accept": (
                    "text/html,application/xhtml+xml,application/xml;q=0.9,"
                    "image/avif,image/webp,*/*;q=0.8"
                ),
                "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.7",
                "Cache-Control": "no-cache",
            }
        )

    def _create_session(self):
        """Create one reusable scraper session, with a safe requests fallback."""
        self.session_backend = "requests"
        self.session_backend_error = ""
        if not self.use_cloudscraper:
            self.session_backend_error = "disabled by config"
            return requests.Session()
        if cloudscraper is None:
            self.session_backend_error = CLOUDSCRAPER_IMPORT_ERROR or "not installed"
            return requests.Session()
        try:
            session = cloudscraper.create_scraper(
                browser={
                    "browser": "chrome",
                    "platform": "windows",
                    "mobile": False,
                }
            )
            if session is None or not hasattr(session, "get"):
                raise RuntimeError("create_scraper returned an invalid session")
            self.session_backend = "cloudscraper"
            return session
        except Exception as exc:
            self.session_backend_error = "%s: %s" % (type(exc).__name__, exc)
            return requests.Session()

    def _request_text(self, path, params=None, expected=""):
        if self.session is None:
            self._reset_session()
        errors = []
        self.last_host_failures = []
        candidates = [self.host] + [
            host for host in self.host_candidates if host != self.host
        ]
        for origin in candidates:
            try:
                source, final_url = self._request_origin(
                    origin, path, params, expected=expected
                )
                self.host = self._origin(final_url) or origin
                return source, final_url
            except Exception as exc:
                kind = self._failure_kind(exc)
                detail = "%s: %s" % (self._hostname(origin), exc)
                self.last_host_failures.append(
                    {"origin": origin, "kind": kind, "message": str(exc)}
                )
                errors.append("[%s] %s" % (kind, detail))
        raise RuntimeError("；".join(errors) or "請求失敗")

    def _request_origin(self, origin, path, params=None, expected=""):
        url = urljoin(origin + "/", str(path or "").lstrip("/"))
        current_url = url
        current_params = params
        redirect_count = 0
        while True:
            try:
                response = self.session.get(
                    current_url,
                    params=current_params,
                    headers=self._site_headers(current_url),
                    timeout=self.timeout,
                    allow_redirects=False,
                )
                current_params = None
                if response.status_code in (301, 302, 303, 307, 308):
                    target = urljoin(response.url, response.headers.get("Location") or "")
                    if not target:
                        response.raise_for_status()
                    source_host = self._hostname(response.url)
                    target_host = self._hostname(target)
                    known_hosts = {self._hostname(item) for item in self.host_candidates}
                    if target_host != source_host and (
                        not self.allow_domain_redirect or target_host not in known_hosts
                    ):
                        raise DomainRedirectError(
                            "域名重定向 %s -> %s 已阻止；不同域名不共用 Cookie，"
                            "请按当前地区选择 host 并为该域名重新验证"
                            % (source_host, target_host)
                        )
                    redirect_count += 1
                    if redirect_count > 4:
                        raise RuntimeError("域名重定向次数过多")
                    current_url = target
                    continue
                source = self._decode_response(response)
                if self._is_challenge(source) or response.status_code in (403, 429, 503):
                    ray = str(response.headers.get("CF-RAY") or "").strip()
                    suffix = " CF-RAY=%s" % ray if ray else ""
                    raise CFBlockedError(
                        "Cloudflare %s 拦截%s；Cookie 可能已因出口网络变化失效，"
                        "请在当前网络、同一域名和相同 User-Agent 下重新验证"
                        % (response.status_code, suffix)
                    )
                response.raise_for_status()
                self._validate_content(source, expected, response.url)
                self._remember_session_cookies(response.url)
                return source, response.url
            except (CFBlockedError, DomainRedirectError):
                raise
            except HostContentError:
                raise
            except requests.RequestException:
                raise
            except Exception as exc:
                if self.session_backend != "cloudscraper":
                    raise
                if self._is_cloudscraper_challenge_error(exc):
                    raise CFBlockedError(
                        "cloudscraper 未能完成 Cloudflare 挑战；需要在当前出口、"
                        "相同域名和相同 User-Agent 下人工验证并复用 Cookie"
                    ) from exc
                raise requests.RequestException(
                    "cloudscraper 请求失败: %s" % exc
                ) from exc

    def _site_headers(self, url):
        origin = self._origin(url) or self.host
        headers = {"Referer": origin + "/"}
        cookie = self._request_cookie(url)
        if cookie:
            headers["Cookie"] = cookie
        return headers

    def _playback_headers(self, media_url, page_url):
        page_origin = self._origin(page_url) or self.host
        headers = {
            "User-Agent": self.user_agent,
            "Referer": page_url,
            "Origin": page_origin,
            "Accept": "*/*",
            "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.7",
        }
        cookie = self._cookie_for_url(media_url, self.media_cookie_by_host)
        if (
            not cookie
            and self.forward_site_cookie_to_player
            and self._hostname(media_url) == self._hostname(page_url)
        ):
            cookie = self._request_cookie(page_url)
        if cookie:
            headers["Cookie"] = cookie
        return headers

    def _request_cookie(self, url):
        configured = self._cookie_for_url(url, self.cookie_by_host)
        hostname = self._hostname(url)
        jar_values = []
        if self.session is not None and hostname:
            for item in self.session.cookies:
                domain = str(getattr(item, "domain", "") or "").lstrip(".").lower()
                if domain and (hostname == domain or hostname.endswith("." + domain)):
                    jar_values.append("%s=%s" % (item.name, item.value))
        return self._merge_cookie_headers(configured, "; ".join(jar_values))

    def _remember_session_cookies(self, url):
        hostname = self._hostname(url)
        if self.session is None or not hostname:
            return
        values = []
        for item in self.session.cookies:
            domain = str(getattr(item, "domain", "") or "").lstrip(".").lower()
            if domain and (hostname == domain or hostname.endswith("." + domain)):
                values.append("%s=%s" % (item.name, item.value))
        if not values:
            return
        with self._cookie_lock:
            current = self.cookie_by_host.get(hostname, "")
            merged = self._merge_cookie_headers(current, "; ".join(values))
            if not merged or merged == current:
                return
            self.cookie_by_host[hostname] = merged
        self._save_cookie_cache()

    def _default_cookie_cache_path(self):
        if not self.cookie_cache:
            return ""
        try:
            from java import jclass

            path_class = jclass("com.github.catvod.utils.Path")
            return str(path_class.files("hanime1_v4_cookie.json").getAbsolutePath())
        except Exception:
            return ""

    def _load_cookie_cache(self):
        path = str(self.cookie_cache_path or "").strip()
        if not self.cookie_cache or not path:
            self._cookie_cache_status = "disabled" if not self.cookie_cache else "no-path"
            return {}
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            if not isinstance(data, dict):
                data = {}
            cookies = self._cookie_map(data.get("cookies"))
            user_agent = str(data.get("user_agent") or "").strip()
            if cookies:
                self._cookie_cache_saved_at = float(data.get("updated") or 0)
                self._cookie_cache_signature = self._cookie_cache_digest(cookies, user_agent)
                self._cookie_cache_status = "loaded"
                self._cookie_cache_log("loaded", count=len(cookies))
            else:
                self._cookie_cache_status = "empty"
            return {"cookies": cookies, "user_agent": user_agent}
        except FileNotFoundError:
            self._cookie_cache_status = "missing"
            return {}
        except Exception as exc:
            self._cookie_cache_status = "read-error"
            self._cookie_cache_log("read-error", error=type(exc).__name__)
            return {}

    def _save_cookie_cache(self, force=False):
        path = str(self.cookie_cache_path or "").strip()
        if not self.cookie_cache or not path:
            return False
        with self._cookie_lock:
            cookies = dict(self.cookie_by_host)
            user_agent = self.user_agent
        if not cookies:
            return False
        signature = self._cookie_cache_digest(cookies, user_agent)
        now = time.time()
        if (
            not force
            and signature == self._cookie_cache_signature
            and now - self._cookie_cache_saved_at < self.cookie_writeback_interval
        ):
            return True
        temp_path = path + ".tmp"
        try:
            parent = os.path.dirname(path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            descriptor = os.open(temp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "version": 1,
                        "updated": int(now),
                        "user_agent": user_agent,
                        "cookies": cookies,
                    },
                    handle,
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
            os.replace(temp_path, path)
            self._cookie_cache_signature = signature
            self._cookie_cache_saved_at = now
            self._cookie_cache_status = "saved"
            self._cookie_cache_log("saved", count=len(cookies))
            return True
        except Exception as exc:
            self._cookie_cache_status = "write-error"
            self._cookie_cache_log("write-error", error=type(exc).__name__)
            try:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
            except Exception:
                pass
            return False

    def _clear_cookie_cache(self):
        path = str(self.cookie_cache_path or "").strip()
        if not path:
            return
        try:
            if os.path.exists(path):
                os.remove(path)
            self._cookie_cache_signature = ""
            self._cookie_cache_saved_at = 0.0
            self._cookie_cache_status = "cleared"
            self._cookie_cache_log("cleared")
        except Exception as exc:
            self._cookie_cache_status = "clear-error"
            self._cookie_cache_log("clear-error", error=type(exc).__name__)

    @staticmethod
    def _cookie_cache_digest(cookies, user_agent):
        return json.dumps(
            {"cookies": cookies, "user_agent": user_agent},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    @staticmethod
    def _cookie_cache_log(state, **fields):
        suffix = " ".join("%s=%s" % item for item in fields.items())
        print("[HANIME1-V6] cookie-cache state=%s%s" % (state, " " + suffix if suffix else ""))

    def _parse_listing(self, source, page, page_url=""):
        doc = self._document(source)
        base_url = page_url or self.host + "/"
        cards = []
        seen = set()
        nodes = doc.xpath(
            "//a[contains(@href,'/watch') and "
            ".//div[contains(concat(' ',normalize-space(@class),' '),' search-videos ')]]"
        )
        if not nodes:
            nodes = doc.xpath("//a[contains(@class,'video-link') and contains(@href,'/watch')]")
        for node in nodes:
            video_id = self._video_id(node.get("href"))
            if not video_id or video_id in seen:
                continue
            seen.add(video_id)
            title = self._clean(
                node.xpath("string(.//div[contains(@class,'home-rows-videos-title')][1])")
                or node.xpath("string(.//div[contains(@class,'title')][1])")
                or node.get("title")
            )
            image = node.xpath("string(.//img[1]/@src)")
            duration = self._clean(
                node.xpath("string(.//div[contains(@class,'duration')][1])")
            )
            cards.append(
                {
                    "vod_id": video_id,
                    "vod_name": title or "Hanime1 %s" % video_id,
                    "vod_pic": urljoin(base_url, image),
                    "vod_remarks": duration,
                }
            )
        page_numbers = []
        for text_value in doc.xpath("//ul[contains(@class,'pagination')]//li//text()"):
            value = self._clean(text_value)
            if value.isdigit():
                page_numbers.append(int(value))
        pagecount = max([page] + page_numbers)
        limit = len(cards)
        return {
            "list": cards,
            "page": page,
            "pagecount": pagecount,
            "limit": limit,
            "total": pagecount * limit if limit else 0,
        }

    def _parse_detail(self, source, video_id, page_url):
        doc = self._document(source)
        title = self._clean(
            doc.xpath("string(//meta[@property='og:title']/@content)")
            or doc.xpath("string(//h3[@id='shareBtn-title'])")
            or doc.xpath("string(//title)")
        )
        title = re.sub(r"\s*-\s*Hanime1\.(?:me|com)\s*$", "", title, flags=re.I)
        cover = doc.xpath("string(//meta[@property='og:image']/@content)")
        if not cover:
            cover = doc.xpath("string(//video[@id='player']/@poster)")
        content = self._clean(doc.xpath("string(//meta[@name='description']/@content)"))
        actor = self._clean(doc.xpath("string(//a[@id='video-artist-name'])"))
        genre = self._clean(
            doc.xpath("string((//a[contains(@href,'genre=')])[last()])")
        )
        tag_values = []
        for node in doc.xpath("//div[contains(@class,'single-video-tag')]/a"):
            value = re.sub(r"\s*\(\d+\)\s*$", "", self._clean(node.text_content()))
            if value and value not in tag_values:
                tag_values.append(value)
        date_match = re.search(
            r"\b(20\d{2})-\d{2}-\d{2}\b", self._clean(doc.text_content())
        )
        sources = self._parse_sources(doc, page_url)
        play_items = []
        for quality, _ in sources:
            label = "%sP" % quality if quality else "自動"
            play_items.append(
                "%s$%s%s/%s" % (label, self.PLAY_PREFIX, video_id, quality or 0)
            )
        if not play_items:
            play_items.append("自動$%s%s/0" % (self.PLAY_PREFIX, video_id))
        return {
            "vod_id": video_id,
            "vod_name": title or "Hanime1 %s" % video_id,
            "vod_pic": urljoin(page_url, cover),
            "type_name": genre,
            "vod_year": date_match.group(1) if date_match else "",
            "vod_actor": actor,
            "vod_content": content,
            "vod_tag": ",".join(tag_values[:24]),
            "vod_play_from": "Hanime1直鏈",
            "vod_play_url": "#".join(play_items),
        }

    def _parse_sources(self, doc, page_url=""):
        values = {}
        base_url = page_url or self.host + "/"
        for node in doc.xpath("//video//source[@src]"):
            url = urljoin(base_url, node.get("src"))
            quality = self._quality(node.get("size"), url)
            if self._is_allowed_media_url(url, page_url):
                values[quality] = url
        if not values:
            for node in doc.xpath("//link[@rel='preload' and @as='video']/@href"):
                url = urljoin(base_url, node)
                if self._is_allowed_media_url(url, page_url):
                    values[self._quality("", url)] = url
        return sorted(values.items(), key=lambda item: item[0], reverse=True)

    def _validate_content(self, source, expected, final_url=""):
        if not expected:
            return
        text = str(source or "")[:300000]
        lowered = text.lower()
        maintenance_markers = (
            "under maintenance",
            "under construction",
            "網站維護",
            "系统维护",
            "暫停服務",
        )
        if any(marker in lowered for marker in maintenance_markers):
            raise HostContentError("maintenance", "返回維護頁")

        has_brand = bool(re.search(r"hanime1\.(?:me|com)", text, re.I))
        has_watch = bool(re.search(r"href=[\"'][^\"']*/watch(?:\?[^\"']*\bv=|/)", text, re.I))
        has_listing = has_watch and bool(
            re.search(r"search-videos|home-rows-videos-title|video-link", text, re.I)
        )
        has_search_shell = has_brand and bool(
            re.search(r"(?:action|href)=[\"'][^\"']*/search", text, re.I)
        )
        has_detail = has_brand and bool(
            re.search(r"og:title|shareBtn-title|id=[\"']player[\"']", text, re.I)
        )
        has_media = has_detail and bool(
            re.search(r"<source\b[^>]+\bsrc=[\"'][^\"']+", text, re.I)
            or re.search(
                r"<link\b(?=[^>]*\brel=[\"']preload[\"'])"
                r"(?=[^>]*\bas=[\"']video[\"'])[^>]*\bhref=[\"'][^\"']+",
                text,
                re.I,
            )
        )
        valid = {
            "listing": has_listing,
            "search": has_listing or has_search_shell,
            "detail": has_detail,
            "media": has_media,
        }.get(expected, True)
        if not valid:
            raise HostContentError(
                "parser_mismatch",
                "%s 未命中 %s 業務標記" % (self._hostname(final_url), expected),
            )

    @staticmethod
    def _failure_kind(exc):
        if isinstance(exc, CFBlockedError):
            return "waf"
        if isinstance(exc, DomainRedirectError):
            return "redirect"
        if isinstance(exc, HostContentError):
            return exc.kind
        if isinstance(exc, requests.Timeout):
            return "timeout"
        if isinstance(exc, requests.RequestException):
            return "network"
        return "runtime"

    def _is_allowed_media_url(self, url, page_url=""):
        parsed = urlsplit(str(url or ""))
        if parsed.scheme != "https" or not parsed.hostname:
            return False
        page_host = self._hostname(page_url)
        media_host = str(parsed.hostname or "").lower()
        return media_host == page_host or media_host in self.media_hosts

    def _document(self, source):
        if isinstance(source, (bytes, bytearray)):
            text = self._decode_bytes(bytes(source))
        else:
            text = str(source or "")
            if "\x00" in text[:256]:
                try:
                    text = self._decode_bytes(text.encode("latin-1"))
                except (UnicodeEncodeError, UnicodeDecodeError):
                    text = text.replace("\x00", "")
        parser = html.HTMLParser(encoding="utf-8", recover=True)
        return html.fromstring(text.encode("utf-8"), parser=parser)

    def _decode_response(self, response):
        return self._decode_bytes(response.content, response.encoding)

    @staticmethod
    def _decode_bytes(raw, declared_encoding=""):
        if not raw:
            return ""
        signatures = (
            (b"\xff\xfe\x00\x00", "utf-32-le"),
            (b"\x00\x00\xfe\xff", "utf-32-be"),
            (b"\xff\xfe", "utf-16-le"),
            (b"\xfe\xff", "utf-16-be"),
        )
        for signature, encoding in signatures:
            if raw.startswith(signature):
                return raw.decode(encoding).lstrip("\ufeff")
        sample = raw[:512]
        if len(sample) >= 16:
            groups = len(sample) // 4
            le32_zeros = sum(
                sample[index] == 0
                for index in range(1, groups * 4)
                if index % 4 in (1, 2, 3)
            )
            be32_zeros = sum(
                sample[index] == 0
                for index in range(0, groups * 4)
                if index % 4 in (0, 1, 2)
            )
            if le32_zeros >= groups * 2:
                return raw.decode("utf-32-le")
            if be32_zeros >= groups * 2:
                return raw.decode("utf-32-be")
        if raw[:4] == b"<\x00\x00\x00":
            return raw.decode("utf-32-le")
        if raw[:4] == b"\x00\x00\x00<":
            return raw.decode("utf-32-be")
        if raw[:2] == b"<\x00":
            return raw.decode("utf-16-le")
        if raw[:2] == b"\x00<":
            return raw.decode("utf-16-be")
        candidates = [str(declared_encoding or "").strip(), "utf-8-sig", "utf-8"]
        for encoding in candidates:
            if not encoding:
                continue
            try:
                return raw.decode(encoding)
            except (LookupError, UnicodeDecodeError):
                continue
        return raw.decode("utf-8", errors="replace")

    def _select_source(self, sources, requested_quality):
        if not sources:
            return None
        target = requested_quality or self.preferred_quality
        if target:
            for item in sources:
                if item[0] == target:
                    return item
            return min(sources, key=lambda item: abs(item[0] - target))
        return sources[0]

    def _play_id(self, value):
        text = str(value or "").strip()
        match = re.match(r"^hanime1://play/(\d+)/(\d+)$", text)
        if match:
            return match.group(1), int(match.group(2))
        video_id = self._video_id(text)
        return (video_id, 0) if video_id else ("", 0)

    def _video_id(self, value):
        text = str(value or "").strip()
        if text.startswith("atvp_detail:"):
            text = text[len("atvp_detail:") :].strip()
        if text.isdigit():
            return text
        match = re.search(r"hanime1://(?:video|play)/(\d+)", text)
        if match:
            return match.group(1)
        try:
            values = parse_qs(urlsplit(text).query).get("v") or []
            if values and str(values[0]).isdigit():
                return str(values[0])
        except Exception:
            pass
        match = re.search(r"(?:[?&]v=|/watch/)(\d+)", text)
        return match.group(1) if match else ""

    def _category_genre(self, tid):
        value = str(tid or "all")
        for type_id, _, genre in self.CATEGORIES:
            if value == type_id or value == genre:
                return genre
        return ""

    def _quality(self, value, url):
        match = re.search(r"(\d{3,4})", str(value or ""))
        if not match:
            match = re.search(r"[-_](\d{3,4})p(?:\.|[/?])", str(url or ""), re.I)
        return int(match.group(1)) if match else 0

    def _is_challenge(self, source):
        text = str(source or "")[:80000].lower()
        signals = (
            "<title>just a moment...</title>",
            "id=\"challenge-form\"",
            "cf-browser-verification",
            "cf-chl-captcha",
            "attention required! | cloudflare",
        )
        return any(signal in text for signal in signals)

    @staticmethod
    def _is_cloudscraper_challenge_error(exc):
        text = ("%s %s" % (type(exc).__name__, exc)).lower()
        return any(
            marker in text
            for marker in (
                "cloudflare",
                "challenge",
                "turnstile",
                "captcha",
                "cf-chl",
            )
        )

    def _player_error(self, message):
        text = self._clean(message) or "播放失敗"
        return {
            "parse": 0,
            "jx": 0,
            "playUrl": "",
            "url": "",
            "header": {},
            "msg": text,
            "error": text,
            "content": text,
        }

    def _empty_page(self, page, message=""):
        result = {
            "list": [],
            "page": page,
            "pagecount": page,
            "limit": 0,
            "total": 0,
        }
        if message:
            result["msg"] = message
        return result

    def _config(self, extend):
        if isinstance(extend, dict):
            return extend
        text = str(extend or "").strip()
        if not text:
            return {}
        candidates = [text]
        try:
            candidates.append(
                base64.urlsafe_b64decode(text + "=" * (-len(text) % 4)).decode("utf-8")
            )
        except Exception:
            pass
        for candidate in candidates:
            try:
                value = json.loads(candidate)
                if isinstance(value, dict):
                    return value
            except Exception:
                continue
        return {"cookie": text} if "=" in text else {}

    def _configured_hosts(self, config):
        explicit = str(config.get("host") or "").strip()
        region = str(config.get("region") or "").strip().lower()
        primary = explicit or self.REGION_HOSTS.get(region) or self.HOST
        values = [primary]
        if not self._bool(config.get("disable_default_fallbacks"), False):
            values.extend(self.DEFAULT_HOSTS)
        fallbacks = config.get("fallback_hosts") or []
        if isinstance(fallbacks, str):
            text = fallbacks.strip()
            if text.startswith("["):
                try:
                    fallbacks = json.loads(text)
                except Exception:
                    fallbacks = re.split(r"[,;\s]+", text)
            else:
                fallbacks = re.split(r"[,;\s]+", text)
        if isinstance(fallbacks, (list, tuple)):
            values.extend(fallbacks)
        result = []
        for value in values:
            host = self._host(value)
            if host and host not in result:
                result.append(host)
        return result or [self.HOST]

    def _configured_media_hosts(self, config):
        values = list(self.MEDIA_HOSTS)
        configured = config.get("media_hosts") or []
        if isinstance(configured, str):
            configured = re.split(r"[,;\s]+", configured.strip())
        if isinstance(configured, (list, tuple)):
            values.extend(configured)
        return {self._hostname(value) for value in values if self._hostname(value)}

    def _cookie_map(self, value):
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return {}
            try:
                value = json.loads(text)
            except Exception:
                return {}
        if not isinstance(value, dict):
            return {}
        result = {}
        for key, cookie in value.items():
            hostname = self._hostname(key)
            text = self._strip_cookie_prefix(cookie)
            if hostname and text:
                result[hostname] = text
        return result

    @classmethod
    def _cookie_for_url(cls, url, cookie_map):
        hostname = cls._hostname(url)
        if not hostname:
            return ""
        if hostname in cookie_map:
            return cookie_map[hostname]
        for domain, cookie in cookie_map.items():
            if hostname.endswith("." + domain.lstrip(".")):
                return cookie
        return ""

    @staticmethod
    def _merge_cookie_headers(*values):
        merged = {}
        for value in values:
            text = Spider._strip_cookie_prefix(value)
            if not text:
                continue
            try:
                parsed = SimpleCookie()
                parsed.load(text)
                for key, morsel in parsed.items():
                    merged[key] = morsel.value
            except Exception:
                for part in text.split(";"):
                    if "=" in part:
                        key, item = part.split("=", 1)
                        merged[key.strip()] = item.strip()
        return "; ".join("%s=%s" % item for item in merged.items())

    @staticmethod
    def _strip_cookie_prefix(value):
        text = str(value or "").strip()
        if text.lower().startswith("cookie:"):
            text = text[len("Cookie:") :].strip()
        return text

    @staticmethod
    def _origin(value):
        try:
            parsed = urlsplit(str(value or ""))
            if parsed.scheme and parsed.netloc:
                return "%s://%s" % (parsed.scheme.lower(), parsed.netloc)
        except Exception:
            pass
        return ""

    @staticmethod
    def _hostname(value):
        text = str(value or "").strip()
        if not text:
            return ""
        try:
            parsed = urlsplit(text if "://" in text else "https://" + text)
            return str(parsed.hostname or "").lower().strip(".")
        except Exception:
            return ""

    @staticmethod
    def _host(value):
        text = str(value or "").strip().rstrip("/")
        try:
            parsed = urlsplit(text)
            if (
                parsed.scheme == "https"
                and parsed.hostname
                and not parsed.username
                and not parsed.password
                and parsed.path in ("", "/")
                and not parsed.query
                and not parsed.fragment
            ):
                return "https://%s" % parsed.netloc
        except Exception:
            pass
        return ""

    @staticmethod
    def _clean(value):
        return " ".join(str(value or "").replace("\xa0", " ").split())

    @staticmethod
    def _page(value):
        try:
            return max(1, int(value))
        except Exception:
            return 1

    @staticmethod
    def _bounded_int(value, default, low, high):
        try:
            return min(high, max(low, int(value)))
        except Exception:
            return default

    @staticmethod
    def _bool(value, default):
        if isinstance(value, bool):
            return value
        if value is None:
            return default
        return str(value).strip().lower() in ("1", "true", "yes", "on")
