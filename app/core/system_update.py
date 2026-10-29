import os
import subprocess
import time
from collections.abc import Callable
from typing import Any

import log
from app.utils.system_utils import SystemUtils
from config import Config


def run_system_update(
    progress_cb: Callable[[int, str], None] | None = None
) -> dict[str, Any]:
    """
    执行一次 Git 系统更新。

    :param progress_cb: 可选进度回调 progress_cb(percent, message)
    :return: 结果字典 {code, updated, msg, branch, old_commit, new_commit, mode, output}
    """

    def report(percent: int, message: str) -> None:
        if progress_cb:
            progress_cb(percent, message)

    if not SystemUtils.is_docker():
        log.warn('【UpdateSystem】当前环境不支持在线更新，仅支持Docker环境')
        return {
            "code": 1,
            "updated": False,
            "msg": "仅支持在Docker环境中执行系统更新",
            "output": "",
        }

    root_path = Config().get_root_path()
    report(5, "开始检查更新...")
    log.info('【UpdateSystem】----------------------------检查更新----------------------------')
    log.info(f'【UpdateSystem】获取系统根目录: {root_path}')

    def run_git(*args: str) -> tuple[int, str, str]:
        """执行git命令，返回(返回码, stdout, 合并输出)"""
        cmd = ["git", "-C", root_path, *args]
        log.info(f'【UpdateSystem】执行：git {" ".join(args)}')
        try:
            ret = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=300,
                env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
            )
        except Exception as err:
            log.error(f'【UpdateSystem】执行 git {" ".join(args)} 异常：{err!s}')
            return 1, "", str(err)
        stdout = (ret.stdout or "").strip()
        output = "\n".join([x for x in [stdout, (ret.stderr or "").strip()] if x])
        for line in output.splitlines():
            log.info(f'【UpdateSystem】>>> {line}')
        return ret.returncode, stdout, output

    # 当前分支
    code, stdout, _ = run_git("rev-parse", "--abbrev-ref", "HEAD")
    branch = stdout if code == 0 and stdout else os.getenv("NASTOOL_VERSION", "master")
    log.info(f'【UpdateSystem】当前分支：{branch}')
    report(15, f"当前分支：{branch}")

    # 更新前的提交
    code, old_commit, _ = run_git("rev-parse", "HEAD")
    if code != 0:
        return {"code": 1, "updated": False,
                "msg": "获取当前版本失败，请查看日志", "output": ""}

    # 默认执行 git pull
    report(35, f"正在拉取 {branch} ...")
    log.info(f'【UpdateSystem】正在拉取当前分支 {branch} ...')
    code, _, pull_output = run_git("pull")
    outputs = [pull_output]
    mode = "pull"

    if code != 0:
        # pull 冲突或失败时，强制以远程分支覆盖本地
        report(50, "拉取失败，正在强制覆盖本地...")
        log.warn('【UpdateSystem】git pull 失败，尝试强制覆盖本地...')
        code, _, fetch_output = run_git("fetch", "origin")
        outputs.append(fetch_output)
        if code != 0:
            return {"code": 1, "updated": False,
                    "msg": "拉取更新失败，请查看日志",
                    "output": "\n".join([x for x in outputs if x])}

        code, _, reset_output = run_git("reset", "--hard", f"origin/{branch}")
        outputs.append(reset_output)
        if code != 0:
            return {"code": 1, "updated": False,
                    "msg": "强制覆盖本地失败，请查看日志",
                    "output": "\n".join([x for x in outputs if x])}
        mode = "force-reset"

    report(70, "正在校验更新结果...")

    # 更新后的提交
    code, new_commit, _ = run_git("rev-parse", "HEAD")
    if code != 0:
        return {"code": 1, "updated": False,
                "msg": "获取更新后版本失败，请查看日志",
                "output": "\n".join([x for x in outputs if x])}

    updated = old_commit != new_commit

    if updated:
        if mode == "force-reset":
            msg = f"本地存在冲突，已强制覆盖为 {branch} 分支最新版本 {new_commit[:8]}"
        else:
            msg = f"已更新到 {branch} 分支最新版本 {new_commit[:8]}"
    elif mode == "force-reset":
        msg = "已强制覆盖本地修改，当前已是最新版本"
    else:
        msg = "当前已是最新版本"
    log.info(f'【UpdateSystem】>>> {msg}')
    report(100, msg)

    return {
        "code": 0,
        "updated": updated,
        "msg": msg,
        "branch": branch,
        "old_commit": old_commit,
        "new_commit": new_commit,
        "mode": mode,
        "output": "\n".join([x for x in outputs if x]),
    }


def get_git_info() -> dict[str, Any]:
    """获取当前 Git 仓库信息"""
    root_path = Config().get_root_path()

    def run_git(*args: str) -> tuple[int, str]:
        cmd = ["git", "-C", root_path, *args]
        ret = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )
        return ret.returncode, (ret.stdout or "").strip()

    try:
        code, branch = run_git("rev-parse", "--abbrev-ref", "HEAD")
        if code != 0:
            return {"code": 1, "msg": "当前目录不是有效的 Git 仓库"}

        _, commit = run_git("rev-parse", "HEAD")
        _, commit_msg = run_git("log", "-1", "--pretty=%s")
        _, commit_time = run_git("log", "-1", "--pretty=%cd",
                                 "--date=format:%Y-%m-%d %H:%M:%S")
        _, remote = run_git("remote", "get-url", "origin")
        _, dirty = run_git("status", "--porcelain")

        return {
            "code": 0,
            "is_docker": SystemUtils.is_docker(),
            "branch": branch,
            "commit": commit,
            "short_commit": commit[:8],
            "commit_msg": commit_msg,
            "commit_time": commit_time,
            "remote": remote,
            "dirty": bool(dirty),
        }
    except Exception as e:
        log.exception("获取 Git 信息失败")
        return {"code": 1, "msg": f"获取 Git 信息失败：{e!s}"}


def check_system_update() -> dict[str, Any]:
    """
    检查当前分支是否有远程更新。

    只执行 git fetch 和比较，不会修改本地代码（不会 pull/reset）。
    返回的日志只包含远程更新信息（提交日志），不列出本地改动的文件。
    """
    root_path = Config().get_root_path()
    logs: list[dict[str, Any]] = []

    def add(text: str, level: str = "INFO") -> None:
        logs.append({
            "time": time.strftime("%H:%M:%S"),
            "level": level,
            "text": text,
        })

    def run_git(*args: str, timeout: int = 120) -> tuple[int, str, str]:
        cmd = ["git", "-C", root_path, *args]
        try:
            ret = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
            )
        except Exception as err:
            return 1, "", str(err)
        return ret.returncode, (ret.stdout or "").strip(), (ret.stderr or "").strip()

    try:
        code, branch, _ = run_git("rev-parse", "--abbrev-ref", "HEAD", timeout=10)
        if code != 0 or not branch:
            add("当前目录不是有效的 Git 仓库", "ERROR")
            return {"code": 1, "has_update": False,
                    "msg": "当前目录不是有效的 Git 仓库", "logs": logs}

        if branch == "HEAD":
            branch = os.getenv("NASTOOL_VERSION", "master")
        add(f"当前分支：{branch}")

        # 上游分支（未配置时回退到 origin/<branch>）
        up_code, upstream, _ = run_git(
            "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}", timeout=10
        )
        if up_code != 0 or not upstream or "/" not in upstream:
            upstream = f"origin/{branch}"

        # 拉取远程引用（不修改工作区）
        add("正在获取远程更新...")
        code, _, fetch_err = run_git("fetch", "--prune", "origin")
        if code != 0:
            add(f"获取远程更新失败：{fetch_err or '请检查网络或代理配置'}", "ERROR")
            return {"code": 1, "has_update": False,
                    "msg": "获取远程更新失败，请检查网络", "logs": logs}

        code, behind_text, _ = run_git("rev-list", "--count", f"HEAD..{upstream}")
        if code != 0:
            add(f"无法比较远程分支 {upstream}", "ERROR")
            return {"code": 1, "has_update": False,
                    "msg": f"无法比较远程分支 {upstream}", "logs": logs}
        try:
            behind = int(behind_text or 0)
        except ValueError:
            behind = 0

        code, ahead_text, _ = run_git("rev-list", "--count", f"{upstream}..HEAD")
        try:
            ahead = int(ahead_text or 0) if code == 0 else 0
        except ValueError:
            ahead = 0

        commits: list[str] = []
        if behind > 0:
            # 只展示远程的新提交日志
            _, commit_text, _ = run_git(
                "log", "--no-decorate", "--date=format:%Y-%m-%d",
                "--pretty=format:%h  %s  (%an, %ad)",
                "-n", "100", f"HEAD..{upstream}",
            )
            commits = [line for line in commit_text.splitlines() if line.strip()]
            add(f"发现 {behind} 个新提交（{upstream}）：")
            for line in commits:
                add(line)
            # 只有确实有远程更新时，才提示本地改动可能被强制覆盖
            _, dirty, _ = run_git("status", "--porcelain", timeout=10)
            if dirty:
                add("检测到未提交的本地修改，更新时可能被强制覆盖", "WARN")
        else:
            add("当前已是最新版本")

        if ahead > 0:
            add(f"本地有 {ahead} 个提交领先远程", "WARN")

        return {
            "code": 0,
            "has_update": behind > 0,
            "behind": behind,
            "ahead": ahead,
            "branch": branch,
            "upstream": upstream,
            "commits": commits,
            "logs": logs,
            "msg": f"发现 {behind} 个新提交" if behind > 0 else "当前已是最新版本",
        }
    except Exception as e:
        log.exception("检查系统更新失败")
        add(f"检查更新失败：{e!s}", "ERROR")
        return {"code": 1, "has_update": False,
                "msg": f"检查更新失败：{e!s}", "logs": logs}
