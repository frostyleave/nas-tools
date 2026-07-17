from app.utils.types import MediaType


class Constants(object):
    """
    常量类
    """

    # 种子名/文件名要素分隔字符
    SPLIT_CHARS = r"\.|\s+|\(|\)|\[|]|-|\+|【|】|/|;|&|\||#|_|「|」"

    # TMDB域名地址
    TMDB_API_DOMAINS = [
        'api.themoviedb.org', 
        'api.tmdb.org', 
        "tmdb.org"
    ]

    # 支持的媒体文件后缀格式
    RMT_MEDIAEXT = ['.mp4', '.mkv', '.ts', '.iso',
                    '.rmvb', '.avi', '.mov', '.mpeg',
                    '.mpg', '.wmv', '.3gp', '.asf',
                    '.m4v', '.flv', '.m2ts', '.strm',
                    '.tp']
    # 支持的字幕文件后缀格式
    RMT_SUBEXT = ['.srt', '.ass', '.ssa']

    # 繁体字幕正则
    ZHTW_SUB_RE = r"([.\[(](((zh[-_])?(hk|tw|cht|tc))" \
                r"|繁[体中]?)[.\])])" \
                r"|繁体中[文字]|中[文字]繁体|繁[体體日]" \
                r"|(?<![a-z0-9])big5(?![a-z0-9])"
    
    # 支持的音轨文件后缀格式
    RMT_AUDIO_TRACK_EXT = ['.mka']

    # 下载文件转移检查时间间隔，
    PT_TRANSFER_INTERVAL = 300

    # 电影类型关键字
    MOVIE_TYPES = [
        'MOV', 
        '电影', 
        MediaType.MOVIE
    ]

    # 电视剧类型关键字
    TVT_YPES = [
        'TV', 
        '电视剧',
        MediaType.TV
    ]

    # 类型常量枚举映射
    MEDIA_TYPE_MAP = {
        'TV': MediaType.TV,
        'MOV': MediaType.MOVIE,
        'MOVIE': MediaType.MOVIE,
        'ANI': MediaType.ANIME,
        'ANIME': MediaType.ANIME,
    }
