# //@name:小心儿悠悠(Direct)
# //@id:0b76499ed935a055c5ef748b69f07d317e283c8a
# //@version:1
# //@format:python-spider/source-v1
from base.spider import Spider
import requests
import re
import urllib.parse
import json
import time
import uuid

# ==================== 配置区域 ====================
MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 "
    "Mobile/15E148 Safari/604.1"
)

# 允许的入口 host
ALLOWED_HOSTS = {
    "bmlxkyy.com",
    "www.bmlxkyy.com",
    "hongguoduanju.com",
    "www.hongguoduanju.com",
    "novelquickapp.com",
    "www.novelquickapp.com",
}

DEFAULT_MIN_URL_TTL = 900
PLAY_ID_SEP = "__"
CACHE_TTL = 600

# 外部服务配置
FQ_SIGN_API = "http://192.168.31.222:9999"
FQ_SHORT_DRAMA_TAB = 11
FQ_SIGN_TIMEOUT = 25

VIDEO_MODEL_API = "http://192.168.31.222:8800"
VIDEO_MODEL_TIMEOUT = 60

HOME_LIST_LIMIT = 20
PAGE_SIZE = 20
HTTP_TIMEOUT = 20
HTTP_TIMEOUT_SHORT = 12

FILTER_TAG_KEYS = ["背景", "主题", "设定"]
# ==================== 配置区域结束 ====================

# 模块级缓存
_CACHE = {
    "home": {"ts": 0, "videoList": None, "banner": None},
    "cat": {"ts": 0, "recommendList": None, "selectorList": None},
}

class ParseError(Exception):
    pass

# ---------- 通用工具 ----------

def makeHeaders():
    return {
        "User-Agent": MOBILE_UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
    }

def ensureAllowedUrl(url):
    try:
        parsed = urllib.parse.urlparse(url)
        host = parsed.hostname or ""
    except Exception:
        raise ParseError(f"非法链接: {url}")
    host = host.lower()
    if host not in ALLOWED_HOSTS:
        raise ParseError(f"不支持的链接域名: {host}（仅支持红果/番茄分享页）")

def fetchHtml(url, referer=None, retries=3, timeout=HTTP_TIMEOUT):
    ensureAllowedUrl(url)
    headers = makeHeaders()
    if referer:
        headers["Referer"] = referer
        headers["Sec-Fetch-Site"] = "same-origin"
    
    lastErr = None
    for i in range(retries):
        try:
            resp = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
            if resp.status_code != 200:
                raise ParseError(f"HTTP {resp.status_code}")
            return resp.text, resp.url
        except Exception as e:
            lastErr = e
    raise ParseError(f"请求页面失败: {url}: {str(lastErr)}")

def extractRouterData(html):
    match = re.search(r'window\._ROUTER_DATA\s*=\s*(\{[\s\S]*?\})\s*;?\s*</script>', html)
    if not match:
        raise ParseError("页面未包含 window._ROUTER_DATA（可能不是红果页面）")
    try:
        return json.loads(match.group(1))
    except Exception as e:
        raise ParseError(f"window._ROUTER_DATA 解析失败: {str(e)}")

def loaderData(router):
    data = router.get("loaderData")
    if not data or not isinstance(data, dict):
        raise ParseError("loaderData 不存在")
    return data

def findLoaderPage(router, requiredKey):
    ld = loaderData(router)
    for key, value in ld.items():
        if value and isinstance(value, dict) and requiredKey in value:
            return value
    raise ParseError(f"未找到包含 {requiredKey} 的页面")

def findShareLoader(router):
    ld = loaderData(router)
    page = ld.get("video-list-share-ssr_page")
    if page and isinstance(page, dict):
        return page
    return findLoaderPage(router, "pageData")

def shareFromRouter(router):
    page = findShareLoader(router)
    pageData = page.get("pageData")
    if not pageData or not isinstance(pageData, dict):
        raise ParseError("share pageData 不存在")
    return page, pageData

def playerFromRouter(router):
    ld = loaderData(router)
    for key, value in ld.items():
        if value and isinstance(value, dict) and value.get("video_player_info") and isinstance(value.get("video_player_info"), dict):
            return value
    raise ParseError("video_player_info 不存在")

def toInt(value):
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, (int, float)):
        return int(value)
    try:
        text = str(value).strip().replace(",", "")
        return int(float(text))
    except Exception:
        return None

def extractSeriesIdFromUrl(url):
    try:
        u = urllib.parse.urlparse(url)
        q = urllib.parse.parse_qs(u.query)
        if "series_id" in q and q["series_id"]:
            return q["series_id"][0]
        parts = [p for p in u.path.split("/") if p]
        if len(parts) >= 2 and parts[0] == "player":
            return parts[1]
    except Exception:
        pass
    return None

def extractVidFromUrl(url):
    try:
        u = urllib.parse.urlparse(url)
        parts = [p for p in u.path.split("/") if p]
        if len(parts) >= 3 and parts[0] == "player":
            return parts[2]
    except Exception:
        pass
    return None

# ---------- 分享页 / player 页解析 ----------

def seriesFromShare(page, pageData):
    seriesData = pageData.get("series_data")
    if not seriesData or not isinstance(seriesData, dict):
        raise ParseError("share series_data 不存在")
    
    linkParams = page.get("linkParams") or {}
    schemeParams = linkParams.get("schemeParams") or {}
    normalSeriesId = (
        schemeParams.get("video_series_id") or
        seriesData.get("series_id") or
        pageData.get("series_id")
    )
    seriesId = normalSeriesId or schemeParams.get("video_id")
    if not seriesId:
        raise ParseError("未解析到 series_id")
    
    chapterIds = pageData.get("chapter_ids") or []
    if not isinstance(chapterIds, list):
        chapterIds = []
    
    tags = seriesData.get("category_list") or []
    if not isinstance(tags, list):
        tags = []
    category = seriesData.get("category")
    if category and category not in tags:
        tags = [category] + tags
        
    actors = seriesData.get("actor_list") or []
    
    return {
        "series_id": str(seriesId),
        "title": seriesData.get("title") or seriesData.get("series_title"),
        "description": seriesData.get("series_intro"),
        "tags": list(set([str(x) for x in tags if x])),
        "episode_count": toInt(seriesData.get("serial_count") or len(chapterIds)),
        "chapter_ids": [str(x) for x in chapterIds],
        "current_play_url": seriesData.get("play_url"),
        "cover": seriesData.get("series_cover"),
        "actors": actors,
    }

def buildShareUrl(seriesId, vid, uid=None, did=None, uiExpGroup="3", ugToken="#HGjtJKwjmNGko#"):
    def rand():
        return uuid.uuid4().hex
    uid = uid or rand()
    did = did or uid
    
    schemeParams = {
        "video_series_id": str(seriesId),
        "vs_id_type": "1",
        "source": "8",
        "module_name": "share",
        "vid": str(vid),
        "share_toast_vid": str(vid),
        "share_ab_group": 2,
    }
    
    zlink = (
        "https://applink.novelquickapp.com/dVu4P?schemeParams=" +
        urllib.parse.quote(json.dumps(schemeParams))
    )
    
    reportParams = {
        "content_id_key": "material_id",
        "share_timestamp": int(time.time()),
        "entrance": "video_player_share_button",
        "content_id": str(vid),
        "if_full_screen": 0,
        "type": "video_player",
        "read_progress": "0.02",
        "content_type": "short_video",
    }
    
    query = {
        "ui_exp_group": uiExpGroup,
        "uid": uid,
        "zlink": zlink,
        "gd_label": "click_schema_lhft_share_novelread_ios",
        "use_open_launch_app_novel": "1",
        "user_id": "",
        "did": did,
        "share_channel": "copy_link",
        "report_params": json.dumps(reportParams),
        "ug_token": ugToken,
        "_cache": rand(),
    }
    
    return (
        "https://novelquickapp.com/hongguo/ug/pages/video-list-share-ssr?" +
        urllib.parse.urlencode(query)
    )

def mediaUrlExpiry(url):
    try:
        u = urllib.parse.urlparse(url)
        q = urllib.parse.parse_qs(u.query)
        for key in ["x-expires", "expires", "expire"]:
            if key in q and q[key]:
                v = q[key][0]
                if v.isdigit():
                    return int(v)
        for part in u.path.split("/"):
            if re.match(r'^[0-9a-fA-F]{8}$', part):
                value = int(part, 16)
                if 1500000000 <= value <= 4102444800:
                    return value
    except Exception:
        pass
    return None

def inspectMediaUrl(url):
    expiry = mediaUrlExpiry(url)
    if expiry is not None and expiry <= int(time.time()):
        raise ParseError("媒体直链已过期")
    return expiry

def requestShareForVid(seriesId, vid, referer=None, uid=None, minUrlTtl=DEFAULT_MIN_URL_TTL):
    lastErr = None
    bestValid = None
    for attempt in range(5):
        try:
            attemptUid = uid if (attempt == 0 and uid) else uuid.uuid4().hex
            url = buildShareUrl(seriesId, vid, uid=attemptUid)
            html, finalUrl = fetchHtml(url, referer=referer)
            router = extractRouterData(html)
            page, pageData = shareFromRouter(router)
            series = seriesFromShare(page, pageData)
            playUrl = series.get("current_play_url")
            if not playUrl:
                raise ParseError(f"未找到 play_url (vid={vid})")
            expiry = inspectMediaUrl(str(playUrl))
            candidate = {
                "vid": str(vid),
                "url": str(playUrl),
                "source_url": finalUrl,
                "expires_at": expiry,
            }
            if expiry is None or expiry - int(time.time()) >= minUrlTtl:
                return candidate
            if bestValid is None or (expiry or 0) > (bestValid.get("expires_at") or 0):
                bestValid = candidate
            raise ParseError(f"媒体直链即将过期（剩余不足 {minUrlTtl}s）")
        except Exception as e:
            lastErr = e
    if bestValid is not None:
        bestValid["short_ttl"] = True
        return bestValid
    raise ParseError(f"分享页解析失败 (vid={vid}): {str(lastErr)}")

def requestPlayerForVid(seriesId, vid, referer=None, minUrlTtl=DEFAULT_MIN_URL_TTL):
    playerUrl = f"https://hongguoduanju.com/player/{urllib.parse.quote(str(seriesId))}/{urllib.parse.quote(str(vid))}"
    bestValid = None
    for attempt in range(3):
        try:
            html, finalUrl = fetchHtml(playerUrl, referer=referer)
            if not urllib.parse.urlparse(finalUrl).path.startswith("/player/"):
                return None
            page = playerFromRouter(extractRouterData(html))
            info = page.get("video_player_info") or {}
            mainUrl = info.get("main_url")
            if not mainUrl:
                return None
            expiry = inspectMediaUrl(str(mainUrl))
            candidate = {
                "vid": str(vid),
                "url": str(mainUrl),
                "source_url": finalUrl,
                "expires_at": expiry,
            }
            if expiry is None or expiry - int(time.time()) >= minUrlTtl:
                return candidate
            if bestValid is None or (expiry or 0) > (bestValid.get("expires_at") or 0):
                bestValid = candidate
            raise ParseError("player 媒体直链即将过期")
        except Exception:
            if attempt == 2:
                break
    if bestValid is not None:
        bestValid["short_ttl"] = True
        return bestValid
    return None

def loadSeriesSeed(inputUrl):
    html, finalUrl = fetchHtml(inputUrl)
    router = extractRouterData(html)
    host = (urllib.parse.urlparse(finalUrl).hostname or "").lower()
    
    if "novelquickapp.com" in host:
        page, pageData = shareFromRouter(router)
        series = seriesFromShare(page, pageData)
        return series, finalUrl
        
    if "hongguoduanju.com" in host:
        detail = {}
        try:
            page = findLoaderPage(router, "seriesDetail")
            detail = page.get("seriesDetail") or {}
        except Exception:
            detail = {}
        
        vid_list = detail.get("vid_list") or []
        episode_info = detail.get("series_episode_info") or {}
        episode_count = toInt(
            episode_info.get("episode_total_cnt") or
            detail.get("episode_cnt") or
            len(vid_list)
        )
        
        series = {
            "series_id": str(detail.get("series_id") or ""),
            "title": detail.get("series_name"),
            "description": detail.get("series_intro"),
            "cover": detail.get("series_cover"),
            "tags": [str(x) for x in (detail.get("tags") or []) if x],
            "chapter_ids": [str(x) for x in vid_list],
            "episode_count": episode_count,
        }
        if not series["series_id"]:
            sid = extractSeriesIdFromUrl(finalUrl)
            if sid:
                series["series_id"] = sid
        if not series["chapter_ids"]:
            v = extractVidFromUrl(finalUrl)
            if v:
                series["chapter_ids"] = [v]
        return series, finalUrl
        
    raise ParseError(f"不支持的链接域名: {host}")

def detailBySeriesId(seriesId):
    detailUrl = f"https://hongguoduanju.com/detail?series_id={urllib.parse.quote(str(seriesId))}"
    html, finalUrl = fetchHtml(detailUrl)
    router = extractRouterData(html)
    detail = {}
    try:
        page = findLoaderPage(router, "seriesDetail")
        detail = page.get("seriesDetail") or {}
    except Exception:
        detail = {}
        
    if not detail.get("series_id"):
        detail["series_id"] = seriesId
        
    vid_list = detail.get("vid_list") or []
    episode_info = detail.get("series_episode_info") or {}
    episode_count = toInt(
        episode_info.get("episode_total_cnt") or
        detail.get("episode_cnt") or
        len(vid_list)
    )
    
    series = {
        "series_id": str(detail.get("series_id") or seriesId),
        "title": detail.get("series_name"),
        "description": detail.get("series_intro"),
        "cover": detail.get("series_cover"),
        "tags": [str(x) for x in (detail.get("tags") or []) if x],
        "chapter_ids": [str(x) for x in vid_list],
        "episode_count": episode_count,
    }
    return series, finalUrl

# ---------- home/category/search 专用工具 ----------

def fetchHomeRouter(timeout=HTTP_TIMEOUT, retries=2):
    html, _ = fetchHtml("https://hongguoduanju.com/", timeout=timeout, retries=retries)
    router = extractRouterData(html)
    return (loaderData(router).get("page")) or {}

def fetchCategoryRouter(timeout=HTTP_TIMEOUT_SHORT, retries=1):
    html, _ = fetchHtml("https://hongguoduanju.com/category?tag=", timeout=timeout, retries=retries)
    router = extractRouterData(html)
    return (loaderData(router).get("category_page")) or {}

def getHomeData(timeout=HTTP_TIMEOUT, retries=2):
    cache = _CACHE["home"]
    now = time.time()
    if cache["videoList"] is not None and now - cache["ts"] < CACHE_TTL:
        return cache["videoList"] or [], cache["banner"] or []
        
    page = fetchHomeRouter(timeout, retries)
    videoList = page.get("videoList") or []
    homeData = page.get("homeData") or {}
    banner = page.get("bannerList") or homeData.get("banner_list") or []
    
    cache["ts"] = now
    cache["videoList"] = videoList
    cache["banner"] = banner
    return videoList, banner

def getCategoryData(timeout=HTTP_TIMEOUT, retries=2):
    cache = _CACHE["cat"]
    now = time.time()
    if cache["recommendList"] is not None and now - cache["ts"] < CACHE_TTL:
        return cache["recommendList"] or [], cache["selectorList"] or []
        
    page = fetchCategoryRouter(timeout, retries)
    recommend = page.get("recommendList") or []
    selector = page.get("selectorList") or []
    
    cache["ts"] = now
    cache["recommendList"] = recommend
    cache["selectorList"] = selector
    return recommend, selector

def proxiedPic(url, baseURL=""):
    url = str(url or "").strip()
    if not url:
        return ""
    if url.startswith("http://"):
        url = "https://" + url[len("http://"):]
    baseURL = str(baseURL or "").strip().rstrip("/")
    if baseURL and url.startswith("http"):
        urlWithHeaders = f"{url}@Referer=https://p3-reading-sign.fqnovelpic.com"
        return f"{baseURL}/api/proxy/image?url={urllib.parse.quote(urlWithHeaders)}"
    return url

def buildPlaySources(seriesId, vidList):
    vids = [str(v) for v in (vidList or []) if v]
    if not vids:
        return []
    episodes = []
    for i, v in enumerate(vids):
        episodes.append({
            "name": f"第{i + 1}集",
            "playId": f"{seriesId}{PLAY_ID_SEP}{v}"
        })
    return [{"name": "红果直链", "episodes": episodes}]

def formatSeriesSummary(s, withPlay=False):
    seriesId = str(s.get("series_id") or "")
    if not seriesId:
        return {}
    tags = s.get("tags") or []
    if not isinstance(tags, list):
        tags = [tags]
    tags = [str(t) for t in tags if t]
    remarks = s.get("episode_right_text") or (" / ".join(tags[:3]) if tags else "")
    item = {
        "vod_id": seriesId,
        "vod_name": s.get("series_name") or "",
        "vod_pic": proxiedPic(s.get("series_cover") or ""),
        "vod_remarks": remarks,
        "vod_content": s.get("series_intro") or "",
        "type_name": "短剧",
        "vod_year": "",
    }
    if withPlay:
        playSources = buildPlaySources(seriesId, s.get("vid_list"))
        if playSources:
            item["vod_play_sources"] = playSources
    return item

def extractFilterList(selectorList):
    filters = []
    for row in (selectorList or []):
        if not row or not isinstance(row, dict):
            continue
        key = row.get("row_name") or ""
        if not key:
            continue
        if key.startswith("全部"):
            key = key[2:]
        values = [{"name": "全部", "value": ""}]
        for item in (row.get("items") or []):
            if not item or not isinstance(item, dict):
                continue
            name = item.get("show_name")
            if not name:
                continue
            values.append({"name": name, "value": name})
        filters.append({
            "key": key,
            "name": key,
            "init": "",
            "value": values
        })
    return filters

def filterRecommend(recommendList, filters):
    if not filters:
        return list(recommendList)
    tagFilters = {}
    for k in FILTER_TAG_KEYS:
        if k in filters and filters[k]:
            tagFilters[k] = filters[k]
    vals = list(tagFilters.values())
    if not vals:
        return list(recommendList)
    filtered = []
    for s in recommendList:
        tags = set([t for t in (s.get("tags") or []) if isinstance(t, str)])
        if all(v in tags for v in vals):
            filtered.append(s)
    return filtered

def paginate(items, page, size=PAGE_SIZE):
    total = len(items)
    try:
        page = max(1, int(page or 1))
    except Exception:
        page = 1
    pagecount = max(1, (total + size - 1) // size) if total else 0
    start = (page - 1) * size
    return items[start:start + size], total, pagecount

def looksLikeUrl(s):
    return bool(s and (s.startswith("http://") or s.startswith("https://")))

def splitPlayId(playId):
    if PLAY_ID_SEP in playId:
        parts = playId.split(PLAY_ID_SEP, 1)
        return parts[0], parts[1]
    return playId, ""

def playViaVideoModel(apiBase, seriesId, vid, flag):
    url = f"{apiBase.rstrip('/')}/api/videomodel?vid={urllib.parse.quote(str(vid))}"
    try:
        resp = requests.get(url, headers={"User-Agent": MOBILE_UA}, timeout=VIDEO_MODEL_TIMEOUT)
        if resp.status_code != 200:
            raise ParseError(f"video_model 服务返回 HTTP {resp.status_code}")
        json_data = resp.json()
        if json_data.get("code") != 0:
            raise ParseError(f"video_model 解析失败: {json_data.get('message')}")
        data = json_data.get("data") or {}
        playUrl = data.get("play_url") or data.get("url") or ""
        if not playUrl:
            raise ParseError("video_model 未返回可播放地址")
        header = {"User-Agent": MOBILE_UA}
        if data.get("referer"):
            header["Referer"] = data["referer"]
        return {
            "parse": 0,
            "playUrl": "",
            "url": playUrl,
            "header": header
        }
    except Exception as e:
        print(f"video_model 解析失败，回退 SSR 试看: {e}")
        return playViaSsr(seriesId, vid, flag)

def playViaSsr(seriesId, vid, flag):
    try:
        try:
            data = requestShareForVid(seriesId, vid)
        except Exception as e:
            print(f"分享页解析失败，回退 player 页: {e}")
            data = requestPlayerForVid(seriesId, vid)
            if data is None:
                raise ParseError("分享页与 player 页均未能解析出直链")
        
        url = data.get("url")
        referer = data.get("source_url") or "https://novelquickapp.com/"
        header = {
            "User-Agent": MOBILE_UA,
            "Referer": referer
        }
        return {
            "parse": 0,
            "playUrl": "",
            "url": url,
            "header": header
        }
    except Exception as e:
        print(f"获取播放地址失败: {e}")
        return {
            "parse": 0,
            "playUrl": "",
            "url": "about:blank",
            "header": {}
        }

def searchViaSign(apiBase, keyword, page, searchId="", offset=0, baseURL=""):
    q = {
        "query": keyword,
        "tabType": str(FQ_SHORT_DRAMA_TAB),
        "offset": str(offset),
        "count": str(PAGE_SIZE),
    }
    if searchId:
        q["searchId"] = searchId
        q["passback"] = str(offset)
    
    url = f"{apiBase}/api/fqsearch/books?{urllib.parse.urlencode(q)}"
    headers = {"User-Agent": MOBILE_UA, "Accept": "application/json"}
    try:
        resp = requests.get(url, headers=headers, timeout=FQ_SIGN_TIMEOUT)
        if resp.status_code != 200:
            return None
        data = resp.json().get("data") or {}
        books = data.get("books") or []
        if not isinstance(books, list) or not books:
            return None
            
        hasMore = bool(data.get("hasMore"))
        items = []
        for book in books:
            vod = bookToVod(book, baseURL)
            if vod:
                items.append(vod)
        if not items:
            return None
        return {
            "page": int(page),
            "pagecount": int(page) + (1 if hasMore else 0),
            "total": len(items),
            "list": items
        }
    except Exception as e:
        print(f"searchViaSign error: {e}")
        return None

def bookToVod(book, baseURL=""):
    if not book or not isinstance(book, dict):
        return None
    seriesId = str(book.get("bookId") if book.get("bookId") is not None else book.get("book_id") or "").strip()
    if not seriesId:
        return None
    name = book.get("bookName") or book.get("book_name") or ""
    cover = book.get("coverUrl") or book.get("thumb_url") or book.get("detailPageThumbUrl") or ""
    tags = book.get("tags") or []
    if not isinstance(tags, list):
        tags = []
    remarks = book.get("tagsStr") or ""
    if not remarks and tags:
        remarks = " / ".join(tags[:3])
    intro = book.get("description") or book.get("abstract") or ""
    return {
        "vod_id": seriesId,
        "vod_name": name,
        "vod_pic": proxiedPic(cover, baseURL),
        "vod_remarks": remarks,
        "vod_content": intro,
        "type_name": "短剧",
        "vod_year": "",
    }

# ---------- TVBox Spider 接口类 ----------

class Spider(Spider):
    def getName(self):
        return "小心儿悠悠(Direct)"

    def init(self, extend):
        pass

    def isVideoFormat(self, url):
        pass

    def manualVideoCheck(self):
        pass

    def homeContent(self, filter):
        try:
            videoList, bannerRaw = getHomeData()
            filterList = []
            try:
                _, selectorList = getCategoryData(HTTP_TIMEOUT_SHORT, 1)
                filterList = extractFilterList(selectorList)
            except Exception as e:
                print(f"获取筛选器失败(已降级): {e}")
            
            classes = [{"type_id": "filter", "type_name": "分类"}]
            filters = {"filter": filterList} if filterList else {}
            
            listItems = []
            for s in videoList[:HOME_LIST_LIMIT]:
                fmt = formatSeriesSummary(s, False)
                if fmt:
                    listItems.append(fmt)
            
            banner = []
            for b in bannerRaw[:5]:
                if not b or not isinstance(b, dict):
                    continue
                cover = b.get("background_cover") or b.get("background_cover_mobile") or b.get("series_cover") or ""
                banner.append({
                    "title": b.get("series_name") or "",
                    "vod_id": str(b.get("series_id") or ""),
                    "backgroundImage": proxiedPic(cover),
                    "description": b.get("series_intro") or "",
                })
            return {"class": classes, "filters": filters, "list": listItems, "banner": banner}
        except Exception as e:
            print(f"获取首页数据失败: {e}")
            return {"class": [], "filters": {}, "list": [], "banner": []}

    def homeVideoContent(self):
        return {"list": []}

    def categoryContent(self, cid, pg, filter, ext):
        try:
            categoryId = cid or "recommend"
            page = pg or 1
            filters = ext or {}
            
            recommendList, _ = getCategoryData()
            
            if categoryId == "recommend":
                filtered = list(recommendList)
            else:
                filtered = filterRecommend(recommendList, filters)
                
            pageItems, total, pagecount = paginate(filtered, page)
            listItems = []
            for s in pageItems:
                fmt = formatSeriesSummary(s, True)
                if fmt:
                    listItems.append(fmt)
            
            return {
                "page": int(page),
                "pagecount": pagecount,
                "limit": PAGE_SIZE,
                "total": total,
                "list": listItems
            }
        except Exception as e:
            print(f"获取分类数据失败: {e}")
            return {"page": int(pg or 1), "pagecount": 0, "total": 0, "list": []}

    def detailContent(self, ids):
        try:
            rawInput = str(ids[0]).strip()
            if not rawInput:
                return {"list": []}
            
            series = None
            referer = None
            if looksLikeUrl(rawInput):
                series, referer = loadSeriesSeed(rawInput)
            else:
                series, referer = detailBySeriesId(rawInput)
            
            seriesId = str(series.get("series_id") or "")
            chapterIds = [str(x) for x in (series.get("chapter_ids") or []) if x]
            if not seriesId:
                raise ParseError("未解析到 series_id")
            if not chapterIds:
                raise ParseError("未解析到剧集 vid 列表")
            
            if not series.get("title") or len(chapterIds) <= 1:
                try:
                    first = requestShareForVid(seriesId, chapterIds[0], referer=referer)
                    html, _ = fetchHtml(first["source_url"], referer=referer)
                    page, pageData = shareFromRouter(extractRouterData(html))
                    fresh = seriesFromShare(page, pageData)
                    if fresh.get("title"):
                        series["title"] = fresh["title"]
                    if fresh.get("chapter_ids"):
                        chapterIds = fresh["chapter_ids"]
                        series["chapter_ids"] = chapterIds
                    if fresh.get("cover"):
                        series["cover"] = fresh["cover"]
                except Exception as e:
                    print(f"补充分享页信息失败: {e}")
            
            urls = []
            for i, vid in enumerate(chapterIds):
                playId = f"{seriesId}{PLAY_ID_SEP}{vid}"
                urls.append(f"第{i + 1}集${playId}")
            
            vod_play_url = "#".join(urls)
            actors = series.get("actors") or []
            actor_names = []
            if isinstance(actors, list):
                for a in actors:
                    if isinstance(a, dict) and a.get("nickname"):
                        actor_names.append(a["nickname"])
                    elif isinstance(a, str):
                        actor_names.append(a)
            
            tags = series.get("tags") or []
            remarks = " / ".join(tags) if tags else ""
            
            vod = {
                "vod_id": seriesId,
                "vod_name": series.get("title") or "红果短剧",
                "vod_pic": proxiedPic(series.get("cover") or ""),
                "vod_content": series.get("description") or "",
                "type_name": "短剧",
                "vod_remarks": remarks or f"共{len(chapterIds)}集",
                "vod_year": "",
                "vod_actor": ", ".join(actor_names) if actor_names else "",
                "vod_play_from": "红果直链",
                "vod_play_url": vod_play_url
            }
            return {"list": [vod]}
        except Exception as e:
            print(f"获取红果详情失败: {e}")
            return {"list": []}

    def playerContent(self, flag, id, vipFlags):
        playId = id or ""
        if not playId:
            return {"parse": 0, "playUrl": "", "url": "about:blank", "header": {}}
        seriesId, vid = splitPlayId(playId)
        if not seriesId or not vid:
            return {"parse": 0, "playUrl": "", "url": "about:blank", "header": {}}
            
        apiBase = VIDEO_MODEL_API.strip().rstrip("/")
        if apiBase:
            return playViaVideoModel(apiBase, seriesId, vid, flag)
        return playViaSsr(seriesId, vid, flag)

    def searchContent(self, key, quick, pg=1):
        try:
            keyword = str(key).strip()
            page = pg or 1
            if not keyword:
                return {"page": 1, "pagecount": 0, "total": 0, "list": []}
            
            apiBase = FQ_SIGN_API.strip().rstrip("/")
            if not apiBase:
                print("未配置 FQ_SIGN_API，无法执行 App 全量搜索")
                return {"page": int(page), "pagecount": 0, "total": 0, "list": []}
            
            print(f"App 全量搜索红果短剧: keyword={keyword}, page={page}")
            try:
                off = (max(1, int(page)) - 1) * PAGE_SIZE
                signed = searchViaSign(apiBase, keyword, page, offset=off)
                if signed is not None:
                    return signed
                return {
                    "page": int(page),
                    "pagecount": int(page),
                    "total": 0,
                    "list": []
                }
            except Exception as e:
                print(f"App 全量搜索失败: {e}")
                return {"page": int(page), "pagecount": 0, "total": 0, "list": []}
        except Exception as e:
            print(f"搜索视频失败: {e}")
            return {"page": int(pg or 1), "pagecount": 0, "total": 0, "list": []}
