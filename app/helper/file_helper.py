import os
import re
import shutil

from urllib.parse import unquote

import log

from config import RMT_AUDIO_TRACK_EXT, RMT_MEDIAEXT, RMT_SUBEXT
from app.utils.path_utils import PathUtils
from app.utils.string_utils import StringUtils
from app.utils.system_utils import SystemUtils
from app.utils.types import OsType


class FileHelper:

    @staticmethod
    def delete_media_file(filedir, filename):
        """
        删除媒体文件，空目录也会被删除
        """
        filedir = os.path.normpath(filedir).replace("\\", "/")
        file = os.path.join(filedir, filename)
        try:
            if not os.path.exists(file):
                return False, f"{file} 不存在"
            os.remove(file)
            nfoname = f"{os.path.splitext(filename)[0]}.nfo"
            nfofile = os.path.join(filedir, nfoname)
            if os.path.exists(nfofile):
                os.remove(nfofile)
            # 检查空目录并删除
            if re.findall(r"^S\d{2}|^Season", os.path.basename(filedir), re.I):
                # 当前是季文件夹，判断并删除
                seaon_dir = filedir
                if seaon_dir.count('/') > 1 and not PathUtils.get_dir_files(seaon_dir, exts=RMT_MEDIAEXT):
                    shutil.rmtree(seaon_dir)
                # 媒体文件夹
                media_dir = os.path.dirname(seaon_dir)
            else:
                media_dir = filedir
            # 检查并删除媒体文件夹，非根目录且目录大于二级，且没有媒体文件时才会删除
            if media_dir != '/' \
                    and media_dir.count('/') > 1 \
                    and not re.search(r'[a-zA-Z]:/$', media_dir) \
                    and not PathUtils.get_dir_files(media_dir, exts=RMT_MEDIAEXT):
                shutil.rmtree(media_dir)
            return True, f"{file} 删除成功"
        except Exception as e:
            log.exception(f"[act]{file} 删除失败:")
            return True, f"{file} 删除失败"

    @staticmethod
    def get_sub_path(path_filter, path_dir):
        """
        查询下级子目录
        """
        r = []
        try:
            ft = path_filter or "ALL"
            d = path_dir

            if not d or d == "/":
                if SystemUtils.get_system() == OsType.WINDOWS:
                    partitions = SystemUtils.get_windows_drives()
                    if partitions:
                        dirs = [os.path.join(partition, "/")
                                for partition in partitions]
                    else:
                        dirs = [os.path.join("C:/", f)
                                for f in os.listdir("C:/")]
                else:
                    dirs = [os.path.join("/", f) for f in os.listdir("/")]
            else:
                d = os.path.normpath(unquote(d))
                if not os.path.isdir(d):
                    d = os.path.dirname(d)
                dirs = [os.path.join(d, f) for f in os.listdir(d)]

            dirs.sort()

            for ff in dirs:
                if os.path.isdir(ff):
                    if 'ONLYDIR' in ft or 'ALL' in ft:
                        r.append({
                            "path": ff.replace("\\", "/"),
                            "name": os.path.basename(ff),
                            "type": "dir",
                            "rel": os.path.dirname(ff).replace("\\", "/")
                        })
                else:
                    ext = os.path.splitext(ff)[-1][1:]
                    flag = False
                    if 'ONLYFILE' in ft or 'ALL' in ft:
                        flag = True
                    elif "MEDIAFILE" in ft and f".{str(ext).lower()}" in RMT_MEDIAEXT:
                        flag = True
                    elif "SUBFILE" in ft and f".{str(ext).lower()}" in RMT_SUBEXT:
                        flag = True
                    elif "AUDIOTRACKFILE" in ft and f".{str(ext).lower()}" in RMT_AUDIO_TRACK_EXT:
                        flag = True
                    if flag:
                        r.append({
                            "path": ff.replace("\\", "/"),
                            "name": os.path.basename(ff),
                            "type": "file",
                            "rel": os.path.dirname(ff).replace("\\", "/"),
                            "ext": ext,
                            "size": StringUtils.str_filesize(os.path.getsize(ff))
                        })

        except Exception as e:
            log.exception("[act]加载路径失败:")
        return r
