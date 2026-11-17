"""站点统计相关表改为以站点地址为主键

SITE_FAVICON、SITE_USER_INFO_STATS、SITE_USER_SEEDING_INFO 统一以 URL 作为主键，
站点名称只保留为展示字段。

Revision ID: b7f4d2c9a1e3
Revises: c4d2e9f7a1b3
Create Date: 2026-11-17 22:30:00.000000

"""
from alembic import op

# revision identifiers, used by Alembic.
revision = 'b7f4d2c9a1e3'
down_revision = 'c4d2e9f7a1b3'
branch_labels = None
depends_on = None


def _table_info(conn, table):
    return conn.exec_driver_sql(f'PRAGMA table_info("{table}")').fetchall()


def _table_exists(conn, table):
    return bool(_table_info(conn, table))


def _primary_keys(conn, table):
    rows = sorted(_table_info(conn, table), key=lambda row: row[5])
    return [row[1] for row in rows if row[5]]


def _row_count(conn, table):
    return conn.exec_driver_sql(f'SELECT COUNT(*) FROM "{table}"').scalar()


def _cleanup_leftover(conn, table):
    """
    处理上次中断遗留的临时表：主表已有数据时直接删除临时表，
    主表为空（重建到一半中断）时用临时表恢复数据
    """
    old_table = f"_{table}_old"
    if not _table_exists(conn, old_table):
        return
    if _table_exists(conn, table) and _row_count(conn, table) > 0:
        conn.exec_driver_sql(f'DROP TABLE "{old_table}"')
        return
    conn.exec_driver_sql(f'DROP TABLE IF EXISTS "{table}"')
    conn.exec_driver_sql(f'ALTER TABLE "{old_table}" RENAME TO "{table}"')


def _rebuild(conn, table, create_sql, columns):
    """
    重建表并保留已有数据：只拷贝新旧表都存在的列
    """
    old_columns = {row[1] for row in _table_info(conn, table)}
    columns = [column for column in columns if column in old_columns]
    quoted = ", ".join(f'"{column}"' for column in columns)
    old_table = f"_{table}_old"
    conn.exec_driver_sql(f'DROP TABLE IF EXISTS "{old_table}"')
    conn.exec_driver_sql(f'ALTER TABLE "{table}" RENAME TO "{old_table}"')
    conn.exec_driver_sql(create_sql)
    conn.exec_driver_sql(
        f'INSERT INTO "{table}" ({quoted}) SELECT {quoted} FROM "{old_table}"')
    conn.exec_driver_sql(f'DROP TABLE "{old_table}"')


def _drop_invalid_url(conn, table):
    conn.exec_driver_sql(
        f'DELETE FROM "{table}" WHERE "URL" IS NULL OR TRIM("URL") = \'\'')


def _dedupe_by_url(conn, table, keep_latest=True):
    """
    同一地址只保留一条记录，默认保留最新的一条
    """
    keep = "MAX" if keep_latest else "MIN"
    conn.exec_driver_sql(
        f'DELETE FROM "{table}" WHERE rowid NOT IN '
        f'(SELECT {keep}(rowid) FROM "{table}" GROUP BY "URL")')


def _dedupe_favicon(conn, table):
    """
    同一地址只保留一条图标记录，优先保留已缓存有效图标的行
    """
    conn.exec_driver_sql(
        f"""
        DELETE FROM "{table}" WHERE rowid NOT IN (
            SELECT COALESCE(
                MIN(CASE WHEN "FAVICON" LIKE 'data:image/%' THEN rowid END),
                MIN(rowid))
            FROM "{table}" GROUP BY "URL")
        """)


def _need_rebuild(conn, table):
    return _table_exists(conn, table) and _primary_keys(conn, table) != ["URL"]


def upgrade() -> None:
    conn = op.get_bind()

    _cleanup_leftover(conn, "SITE_FAVICON")
    if _need_rebuild(conn, "SITE_FAVICON"):
        _drop_invalid_url(conn, "SITE_FAVICON")
        _dedupe_favicon(conn, "SITE_FAVICON")
        _rebuild(
            conn, "SITE_FAVICON",
            'CREATE TABLE "SITE_FAVICON" ('
            '"URL" TEXT NOT NULL, "SITE" TEXT, "FAVICON" TEXT, '
            'PRIMARY KEY ("URL"))',
            ["URL", "SITE", "FAVICON"])

    _cleanup_leftover(conn, "SITE_USER_INFO_STATS")
    if _need_rebuild(conn, "SITE_USER_INFO_STATS"):
        _drop_invalid_url(conn, "SITE_USER_INFO_STATS")
        _dedupe_by_url(conn, "SITE_USER_INFO_STATS")
        _rebuild(
            conn, "SITE_USER_INFO_STATS",
            'CREATE TABLE "SITE_USER_INFO_STATS" ('
            '"URL" TEXT NOT NULL, "SITE" TEXT, "USERNAME" TEXT, "USER_LEVEL" TEXT, '
            '"JOIN_AT" TEXT, "UPDATE_AT" TEXT, "UPLOAD" INTEGER, "DOWNLOAD" INTEGER, '
            '"RATIO" FLOAT, "SEEDING" INTEGER, "LEECHING" INTEGER, "SEEDING_SIZE" INTEGER, '
            '"BONUS" FLOAT, "MSG_UNREAD" INTEGER, "EXT_INFO" TEXT, '
            'PRIMARY KEY ("URL"))',
            ["URL", "SITE", "USERNAME", "USER_LEVEL", "JOIN_AT", "UPDATE_AT", "UPLOAD",
             "DOWNLOAD", "RATIO", "SEEDING", "LEECHING", "SEEDING_SIZE", "BONUS",
             "MSG_UNREAD", "EXT_INFO"])

    _cleanup_leftover(conn, "SITE_USER_SEEDING_INFO")
    if _need_rebuild(conn, "SITE_USER_SEEDING_INFO"):
        _drop_invalid_url(conn, "SITE_USER_SEEDING_INFO")
        _dedupe_by_url(conn, "SITE_USER_SEEDING_INFO")
        _rebuild(
            conn, "SITE_USER_SEEDING_INFO",
            'CREATE TABLE "SITE_USER_SEEDING_INFO" ('
            '"URL" TEXT NOT NULL, "SITE" TEXT, "SEEDING_INFO" TEXT DEFAULT \'[]\', '
            '"UPDATE_AT" TEXT, PRIMARY KEY ("URL"))',
            ["URL", "SITE", "SEEDING_INFO", "UPDATE_AT"])


def downgrade() -> None:
    pass
