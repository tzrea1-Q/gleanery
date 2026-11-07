"""Agent 只读视图。"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""CREATE VIEW IF NOT EXISTS v_contents AS SELECT DISTINCT
        c.id AS content_id, c.platform, c.url, c.kind, c.title, c.body,
        c.author_id, (SELECT nickname FROM author WHERE id = c.author_id) AS author, c.published_at,
        datetime(c.published_at/1000, 'unixepoch', 'localtime') AS published_local,
        c.likes, c.favorites, c.comments, c.shares, c.plays,
        json_extract(c.ext, '$.coins') AS coins, json_extract(c.ext, '$.danmaku') AS danmaku,
        json_extract(c.ext, '$.duration') AS duration_seconds,
        json_extract(c.ext, '$.tname') AS category,
        coalesce(json_extract(c.ext, '$.counts_approx'), 0) AS counts_approx,
        c.tags, c.completeness,
        (SELECT count(*) FROM comment m WHERE m.content_id = c.id) AS local_comments,
        (SELECT count(*) FROM subtitle s WHERE s.content_id = c.id) AS local_subtitles
        FROM content c""")
    op.execute("""CREATE VIEW IF NOT EXISTS v_comments AS SELECT DISTINCT
        c.id AS comment_id, c.content_id, root.id AS root_comment_id,
        parent.id AS parent_comment_id, (c.root_platform_id IS NOT NULL) AS is_reply,
        c.author_id, a.nickname AS author, c.body, c.published_at,
        datetime(c.published_at/1000, 'unixepoch', 'localtime') AS published_local,
        c.likes, c.reply_count, c.ip_location
        FROM comment c LEFT JOIN author a ON a.id = c.author_id
        LEFT JOIN comment root ON root.platform = c.platform AND root.content_id = c.content_id
            AND root.platform_id = c.root_platform_id
        LEFT JOIN comment parent ON parent.platform = c.platform AND parent.content_id = c.content_id
            AND parent.platform_id = c.parent_platform_id""")
    op.execute("""CREATE VIEW IF NOT EXISTS v_subtitles AS SELECT DISTINCT id AS subtitle_id, content_id, part_title,
        lang, ai_generated, length(text) AS chars, text FROM subtitle""")
    op.execute("""CREATE VIEW IF NOT EXISTS v_datasets AS SELECT DISTINCT d.id AS dataset_id, d.name, d.description,
        d.created_at, d.last_appended_at,
        (SELECT count(*) FROM dataset_item i WHERE i.dataset_id = d.id) AS content_count
        FROM dataset d""")
    op.execute("""CREATE VIEW IF NOT EXISTS v_dataset_items AS SELECT DISTINCT dataset_id, content_id, added_at
        FROM dataset_item""")


def downgrade() -> None:
    # 不支持降级。
    pass
