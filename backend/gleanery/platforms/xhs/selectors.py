"""小红书的页面网址、截获类型与选择器，集中管理。

2026-11-03 真站核对。
"""

HOME = "https://www.xiaohongshu.com/explore"
NOTE_URL = "https://www.xiaohongshu.com/explore/"
# 首页的 #search-input-in-feeds 现在是 AI 搜索框，回车不一定走普通搜索，所以直接打开结果页。
SEARCH_URL = "https://www.xiaohongshu.com/search_result?source=web_explore_feed&keyword="
SEARCH_PATH = "/search_result"
API_HOSTS = ("edith.xiaohongshu.com", "so.xiaohongshu.com", "www.xiaohongshu.com")
"""页面自己的接口域名；只对它们按状态码和响应头判风控，统计上报类域名的 4xx 不算。"""

# 截获类型：接口按路径尾部匹配，不绑定域名和版本号。
SEARCH = "search/notes"
FEED = "feed"
COMMENTS = "comment/page"
SUB_COMMENTS = "comment/sub/page"
USER_ME = "user/me"
PATHS = (SEARCH, FEED, COMMENTS, SUB_COMMENTS, USER_ME)
SSR_NOTE = "ssr:note"
SSR_USER = "ssr:user"
"""驱动合成：整页导航后读 SSR 的登录态。首页加载时页面不调 user/me。"""
NAVIGATE = "page:navigate"
"""驱动合成的主框架跳转记录，只用于判定"跳转到验证页"。"""
UNSAVED = (USER_ME, SSR_USER, NAVIGATE)
"""只用于判定、不交给 sink 的截获：带本人账号信息，或是驱动自己合成的。"""

HEADERS = frozenset({"verifytype", "verifyuuid", "content-type", "retry-after"})
RISK_STATUSES = frozenset({461, 471, 401, 403, 429, 406, 416})
VERIFY_PATHS = ("/website-login/captcha", "/website-login/error", "security-verification")
"""跳到这些路径就是验证页。"""

# 页面状态。Vue 的 ref 要先解包，再经 JSON 往返得到纯数据。
_UNWRAP = (
    "const un = (v, d) => {"
    " if (d > 30 || v === null || typeof v !== 'object') return v;"
    " if ('_rawValue' in v || '_value' in v) return un(v._rawValue ?? v._value, d + 1);"
    " if (Array.isArray(v)) return v.map(x => un(x, d + 1));"
    " const o = {}; for (const k of Object.keys(v)) { if (k !== 'dep' && !k.startsWith('__v')) o[k] = un(v[k], d + 1); }"
    " return o; };"
    "const at = (v, k) => { v = v && (v._rawValue ?? v._value ?? v); return v ? v[k] : undefined; };"
)
USER_STATE = (
    "() => { "
    + _UNWRAP
    + "const user = at(window.__INITIAL_STATE__, 'user'); if (!user) return null;"
    " const info = un(at(user, 'userInfo'), 0) || {};"
    " return {logged_in: un(at(user, 'loggedIn'), 0) ?? null, guest: info.guest ?? null}; }"
)
NOTE_STATE = (
    "id => { "
    + _UNWRAP
    + "const entry = at(at(at(window.__INITIAL_STATE__, 'note'), 'noteDetailMap'), id);"
    " const note = un(at(entry, 'note'), 0);"
    " return note && note.noteId ? JSON.parse(JSON.stringify({note_id: id, note})) : null; }"
)

# 搜索结果是虚拟滚动，DOM 序号会漂移，按笔记 ID 找卡片。
CARD = 'section.note-item:has(a[href*="{id}"]) a.cover'
CARD_RENDER_SECONDS = 5
"""搜索响应到了页面还要渲染一下，等这么久还没有才算不在视口附近。"""
CARD_POLL_SECONDS = 0.25
CARD_SCROLL_STEPS = 40
SCROLL_TOP = "() => window.scrollTo(0, 0)"
FILTER_BUTTON = ".filter"
FILTER_TAG = '.filter-panel .tags >> text="{label}" >> visible=true'
MOUSE_REST = (600, 110)
"""鼠标停放处：结果页"全部 图文 视频 用户"标签与"筛选"之间的空白，离开筛选面板让它收起。"""
SORT = {"default": "综合", "hot": "最多点赞", "new": "最新"}
TIME_FILTER = {"day": "一天内", "week": "一周内", "half_year": "半年内"}

# 笔记弹层与直接打开的笔记页结构相同。
SCROLLER = ".note-scroller"
SCROLL_COMMENTS = "px => document.querySelector('.note-scroller')?.scrollBy(0, px)"
COMMENTS_AT_BOTTOM = (
    "() => { const s = document.querySelector('.note-scroller');"
    " return s ? s.scrollTop + s.clientHeight >= s.scrollHeight - 100 : null; }"
)
SHOW_MORE = ".parent-comment:has(#comment-{id}) .show-more"
""""展开 N 条回复"，展开过一次后变成"展开更多回复"。"""
