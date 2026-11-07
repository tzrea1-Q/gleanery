# 解析器 fixture

文件放在 `<平台>/<kind 中 / 或 : 替换为 __>/<YYYYMMDD>-<用例>.json`。
JSON 包含 `meta` 和 `capture`；元数据记录 platform、kind、url_path、captured_on、source、case、note。
录制素材须使用 `gleanery fixture export` 脱敏并检查；手写素材的 source 为 `handwritten`。
每种类型应覆盖正常、末页或空页、游客或登录失效、风控等情况。
同名 `*.expected.json` 由 `just fixtures-update` 生成，提交前必须人工审阅差异。
可通过 `GLEANERY_LEAK_BLOCKLIST` 指向不入库的本机小号清单，每行一个 UID 或昵称。

## B 站（2026-11-01 录制，小号登录态）

| 类型 | 录制 | 手写 |
|---|---|---|
| `ssr__search` | `normal`、`tags`（2026-11-02，分区 `typename` 和逗号分隔标签 `tag`，`--trim 6`） | `empty`、`last_page` |
| `x__web-interface__wbi__search__type` | `normal`（第 2 页）、`sort_new`（最新发布第 1 页）、`pubtime_30d`（2026-11-02，最新发布、近 30 天） | `last_page`、`empty`、`risk_412`、`risk_voucher` |
| `ssr__video` | `normal`、`no_comments` | — |
| `x__player__wbi__v2` | `with_subtitle`、`no_subtitle` | `guest`、`risk` |
| `subtitle` | `normal` | `empty`、`not_found` |
| `x__v2__reply__wbi__main` | `normal`、`last_page`（`is_end` 为真且无条目）、`empty`（零评论视频） | `login_lost`、`risk` |
| `x__v2__reply__reply` | `normal`、`last_page`（第 2 页） | `empty`、`login_lost`、`risk_412` |

- 两种 SSR 没有游客或风控形态：页面被拦时读不到 SSR，驱动直接抛 `PageChanged`；登录态由同一页的 `nav` 判定，`nav` 不进 sink。
- 搜索结果的 `tag` 按逗号逐个脱敏，保留分隔符；更早录制的 fixture 里，长标签串整串换成了「文」，短的保留原文。
- 搜索的发布时间筛选参数 `pubtime_begin_s`、`pubtime_end_s` 导出时保留原值，测试要用它们核对时间范围；不筛选时页面传 0。
- 搜索在登录态下几乎搜不空（实测乱码关键词也有 1000 条结果），空页只能手写。
- 游客形态实测：新配置目录不登录时，第一次导航 `nav` 就返回 -101，驱动立即停止，所以游客的评论与播放器形态是手写的。
- 每条 fixture 都经过 `test_risk_fixtures.py`：`risk*` 判为风控，`login_lost` 判为登录失效，其余不得有判定。

## 小红书（2026-11-03 录制，小号登录态与游客配置目录）

每条小红书 fixture 的 `meta.verdict` 写明风控判定应得的结果（`risk`、`risk_and_login` 或 null），`tests/platforms/xhs/test_risk_fixtures.py` 逐条核对。

| 类型 | 录制 | 手写 |
|---|---|---|
| `search__notes` | `normal`（综合第 1 页，含 `hot_query` 词卡，`--trim 6`）、`sort_new_week`（最新、一周内）、`last_page`（冷门词加一天内，4 条） | `empty`、`guest`（-104）、`risk`（461 + Verifytype）、`risk_ip`（300012） |
| `feed` | `normal`（图文，弹层）、`video`（视频，弹层） | `empty`（空 `items`）、`guest`（-104）、`risk`（300011） |
| `ssr__note` | `normal`、`no_comments`、`guest`（游客配置目录直接打开） | — |
| `comment__page` | `normal`（`--trim 5`）、`last_page`、`empty`（零评论笔记）、`guest`（游客也拿得到第 1 页，`--trim 3`） | `login_lost`（-100）、`risk`（461 + Verifytype） |
| `comment__sub__page` | `normal`、`last_page` | `empty`、`guest`（-104）、`risk`（471 + Verifytype） |

- 游客实测：配置目录里同样有 `web_session` 这个 Cookie 名；首页的 `user/me` 先回 -101 再回 `guest=true`；搜索页不发 `search/notes`，直接弹登录框；带 token 打开笔记时详情和第 1 页评论照常给。所以游客由驱动合成的 `ssr:user` 判定，`guest` 用例里能录到的都是正常数据（`verdict` 为 null），录不到的照要登录的接口实测返回的 -104 手写。
- `ssr__note` 没有风控形态：被拦时页面跳验证页或读不到 SSR，驱动先由 `page:navigate` 判风控，或直接抛 `PageChanged`，解析器拿不到这类截获。
- 早期探查留下的 `browser-profiles/spike-out/` 只有键结构，不导成 fixture；拿来核对：`feed` 的 `note_card`、`interact_info`，评论条目，搜索条目的键在 10-31 与 11-03 之间没有变化。
