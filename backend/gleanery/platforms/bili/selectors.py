HOME = "https://www.bilibili.com/"
SEARCH_URL = "https://search.bilibili.com/video?keyword="
# 2026-11-02 真站点核对："更多筛选"里的发布时间（全部日期、最近一天、最近一周、最近半年，另有
# 起止日期选择器）选中后写进页面 URL，SSR 和翻页的搜索接口都带上这两个参数，值是秒级时间戳：
# 本地起始日 0 点到结束日 23:59:59。所以直接把参数拼进搜索页 URL，不去点日期选择器。
PUBTIME_BEGIN = "pubtime_begin_s"
PUBTIME_END = "pubtime_end_s"
SEARCH = "x/web-interface/wbi/search/type"
COMMENTS = "x/v2/reply/wbi/main"
REPLIES = "x/v2/reply/reply"
PLAYER = "x/player/wbi/v2"
NAV = "x/web-interface/nav"
PATHS = (SEARCH, COMMENTS, REPLIES, PLAYER, NAV)
HEADERS: frozenset[str] = frozenset()
SEARCH_STATE = "() => window.__pinia?.searchTypeResponse?.searchTypeResponse"
VIDEO_STATE = "() => window.__INITIAL_STATE__?.videoData"

# 待真站点核对。
LOGIN_BUTTON = ".header-avatar-unlogin-entry"  # 2026-10-31 真站点核对：顶栏未登录头像入口
NEXT_PAGE = "text=下一页"
SORT = {"default": "综合", "hot": "最多播放", "new": "最新发布"}
COMMENT_AREA = "bili-comments"
# 2026-11-01 真站点核对：评论线程节点没有 rpid 属性，rpid 只在元素的 data 属性（JS 对象）上，
# 所以按 rpid 在 shadow DOM 里找到按钮，返回元素句柄，再由 Playwright 真实点击。
_REPLIES_ROOT = (
    "const thread = [...(document.querySelector('bili-comments')?.shadowRoot"
    "?.querySelectorAll('bili-comment-thread-renderer') ?? [])]"
    ".find(t => t.data?.rpid_str === rpid);"
    "const replies = thread?.shadowRoot?.querySelector('bili-comment-replies-renderer')?.shadowRoot;"
)
# 楼中楼"共 N 条回复，点击查看"。
REPLY_BUTTON = (
    "rpid => {"
    + _REPLIES_ROOT
    + "return replies?.querySelector('#view-more bili-text-button') ?? null; }"
)
# 楼中楼展开后的分页"下一页"，每页 10 条。
REPLY_NEXT_PAGE = (
    "rpid => {"
    + _REPLIES_ROOT
    + "return [...(replies?.querySelectorAll('#pagination-body bili-text-button') ?? [])]"
    ".find(b => b.textContent.trim() === '下一页') ?? null; }"
)
SUBTITLE_FETCH = (
    "async url => { const r = await fetch(url); return {status: r.status, body: await r.text()}; }"
)
