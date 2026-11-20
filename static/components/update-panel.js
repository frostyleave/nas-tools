(function () {
  'use strict';

  const MAX_LOG_ROWS = 5000;

  // 使用 light DOM：样式、jQuery 选择器和 Bootstrap 都依赖页面级 DOM
  const TEMPLATE = `
    <div class="modal modal-blur fade" id="modal-git-update" tabindex="-1" role="dialog" aria-hidden="true"
      aria-labelledby="modal-git-update-title" data-bs-backdrop="static" data-bs-keyboard="false">
      <div class="modal-dialog modal-xl modal-dialog-centered modal-dialog-scrollable" role="document">
        <div class="modal-content">
          <div class="modal-header align-items-start">
            <div class="update-header-main">
              <h5 class="modal-title" id="modal-git-update-title">系统更新</h5>
              <div class="update-subtitle">更新完成后需重启生效</div>
            </div>
            <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="关闭"></button>
          </div>
          <div class="modal-body">
            <div class="update-compare">
              <section class="update-version">
                <div class="update-version-label">当前版本</div>
                <div class="update-version-hash" id="git_panel_commit">—</div>
                <div class="update-version-meta">
                  <span id="git_panel_branch">—</span>
                  <span class="update-sep" aria-hidden="true">·</span>
                  <span id="git_panel_commit_time">—</span>
                </div>
                <div class="update-version-msg" id="git_panel_commit_msg">—</div>
              </section>
              <div class="update-arrow" aria-hidden="true">
                <i class="ti ti-chevrons-right update-arrow-next"></i>
                <i class="ti ti-circle-check update-arrow-done"></i>
                <span class="update-delta" id="git_panel_delta">待检测</span>
              </div>
              <section class="update-version">
                <div class="update-version-label">
                  <span>远程版本</span>
                  <span class="update-ref" id="git_panel_remote_ref"></span>
                </div>
                <div class="update-version-hash" id="git_panel_remote_hash">—</div>
                <div class="update-version-meta" id="git_panel_remote_meta">尚未检测</div>
                <div class="update-version-msg" id="git_panel_remote_msg">点击「检测更新」获取远程分支的最新提交</div>
              </section>
            </div>
            <div class="update-notice" id="git_panel_notice" hidden>
              <i class="ti ti-alert-triangle"></i>
              <span id="git_panel_notice_text"></span>
            </div>
            <section class="update-section">
              <div class="update-section-head">
                <h6 class="update-section-title">更新内容</h6>
                <span class="update-count" id="git_panel_commit_count">尚未检测</span>
              </div>
              <ul class="update-commit-list" id="git_panel_commit_list">
                <li class="update-commit-empty">
                  <i class="ti ti-list-check"></i>
                  <span>检测后可查看远程新增的提交</span>
                </li>
              </ul>
            </section>
            <section class="update-log">
              <button type="button" class="update-log-toggle" id="git_panel_log_toggle" aria-expanded="false"
                aria-controls="git_panel_log_body">
                <i class="ti ti-chevron-right update-log-chevron"></i>
                <span>更新日志</span>
              </button>
              <div class="update-log-body" id="git_panel_log_body" hidden>
                <div class="update-log-scroll" id="git_panel_log_scroll" role="log" aria-live="off"
                  aria-label="更新过程日志">
                  <div class="update-log-content" id="git_panel_log_content">
                    <div class="update-log-empty">尚未开始</div>
                  </div>
                </div>
              </div>
              <div class="update-progress-row" id="git_panel_progress_row" hidden>
                <div class="progress update-progress" id="git_panel_progress_track" role="progressbar"
                  aria-label="更新进度" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0">
                  <div class="progress-bar" id="git_panel_progress" style="width:0%"></div>
                </div>
                <span class="update-progress-value" id="git_panel_progress_value">0%</span>
              </div>
            </section>
          </div>
          <div class="modal-footer update-footer">
            <span class="update-status text-muted" id="git_panel_status" role="status"
              aria-live="polite">尚未检测远程更新</span>
            <button type="button" class="btn btn-ghost-secondary" data-bs-dismiss="modal">关闭</button>
            <button type="button" class="btn btn-primary" id="git_panel_action_btn">检测更新</button>
          </div>
        </div>
      </div>
    </div>
  `;

  class UpdatePanel extends HTMLElement {
    constructor() {
      super();
      this._abort = null;
      this._pendingLogs = [];
      this._flushTimer = null;
      this._running = false;
      this._checking = false;
      this._hasUpdate = false;
      this._isDocker = false;
      this._needsRestart = false;
      this._needsReload = false;
      this._dirty = false;
      this._ahead = 0;
      this._behind = 0;
    }

    connectedCallback() {
      if (this._ready) {
        return;
      }
      this._ready = true;
      this.innerHTML = TEMPLATE;
      this._bind();
    }

    disconnectedCallback() {
      this._abortStream();
      if (this._flushTimer) {
        cancelAnimationFrame(this._flushTimer);
        this._flushTimer = null;
      }
    }

    // 打开面板；面板由 index.html 持有，切换页面不会丢失检测状态
    open() {
      $("#modal-git-update").modal("show");
      this._refreshInfo();
    }

    _bind() {
      $(this).on("click", "#git_panel_action_btn", () => this._action());
      $(this).on("click", "#git_panel_log_toggle", () => {
        this._expandLog($("#git_panel_log_toggle").attr("aria-expanded") !== "true");
      });
    }

    // 面板状态统一挂在弹窗根节点，样式据此切换版本对比与箭头
    _setState(state) {
      $("#modal-git-update")
        .removeClass("is-checking is-updating is-update is-latest is-error is-done")
        .addClass(state ? "is-" + state : "");
    }

    // 环境限制、本地改动、领先提交合并成一条提示
    _renderNotice() {
      const parts = [];
      if (!this._isDocker) {
        parts.push("当前为本地运行环境，仅 Docker 容器内支持在线更新");
      }
      if (this._dirty) {
        parts.push("检测到未提交的本地修改，更新时可能被强制覆盖");
      }
      if (this._ahead > 0) {
        parts.push(`本地有 ${this._ahead} 个提交领先远程分支`);
      }
      const notice = $("#git_panel_notice");
      if (!parts.length) {
        notice.prop("hidden", true);
        return;
      }
      $("#git_panel_notice_text").text(parts.join("；") + "。");
      notice.prop("hidden", false);
    }

    _syncButtons() {
      const btn = $("#git_panel_action_btn");
      if (!btn.length) {
        return;
      }
      btn.prop("disabled", false).removeAttr("title");
      if (this._running) {
        btn.prop("disabled", true).text("更新中…");
        return;
      }
      if (this._checking) {
        btn.prop("disabled", true).text("检测中…");
        return;
      }
      if (this._needsRestart) {
        btn.text("立即重启生效");
        return;
      }
      if (this._needsReload) {
        btn.text("刷新页面");
        return;
      }
      if (this._hasUpdate) {
        btn.text("开始更新");
        if (!this._isDocker) {
          btn.prop("disabled", true).attr("title", "仅 Docker 环境支持在线更新");
        }
        return;
      }
      btn.text("检测更新");
    }

    _action() {
      if (this._running || this._checking) {
        return;
      }
      if (this._needsRestart) {
        this._restart();
        return;
      }
      if (this._needsReload) {
        window.location.reload(true);
        return;
      }
      if (this._hasUpdate) {
        this._startUpdate();
        return;
      }
      this._checkUpdate();
    }

    // 状态栏统一入口：状态与结果共用一处，通过文字颜色区分
    _setStatus(text, type) {
      const el = $("#git_panel_status");
      if (!el.length) {
        return;
      }
      const colors = {
        info: "text-info",
        success: "text-success",
        warning: "text-warning",
        danger: "text-danger"
      };
      el.removeClass("text-muted text-info text-success text-warning text-danger")
        .addClass(colors[type] || "text-muted")
        .text(text || "")
        .attr("title", text || "");
    }

    _setProgress(value, visible) {
      const percent = Math.max(0, Math.min(100, Number(value) || 0));
      $("#git_panel_progress").css("width", percent + "%");
      $("#git_panel_progress_track").attr("aria-valuenow", Math.round(percent));
      $("#git_panel_progress_value").text(Math.round(percent) + "%");
      $("#git_panel_progress_row").prop("hidden", !visible);
    }

    _expandLog(expand) {
      $("#git_panel_log_body").prop("hidden", !expand);
      $("#git_panel_log_toggle").attr("aria-expanded", expand ? "true" : "false");
      if (expand) {
        requestAnimationFrame(() => this._scrollToLog());
      }
    }

    // 展开日志后把日志区带进弹窗可视范围，窄屏下避免日志被页脚挡住
    _scrollToLog() {
      const body = this.querySelector("#modal-git-update .modal-body");
      const log = this.querySelector("#git_panel_log_body");
      if (!body || !log || log.hidden) {
        return;
      }
      const bodyRect = body.getBoundingClientRect();
      let bottom = log.getBoundingClientRect().bottom;
      const progress = this.querySelector("#git_panel_progress_row");
      if (progress && !progress.hidden) {
        bottom = Math.max(bottom, progress.getBoundingClientRect().bottom);
      }
      const delta = bottom - bodyRect.bottom;
      if (delta > 0) {
        body.scrollTop += delta + 8;
      }
    }

    _resetLog(text) {
      this._pendingLogs = [];
      if (this._flushTimer) {
        cancelAnimationFrame(this._flushTimer);
        this._flushTimer = null;
      }
      $("#git_panel_log_content").html(
        `<div class="update-log-empty">${this._escape(text || "尚未开始")}</div>`
      );
      this._setProgress(0, false);
    }

    // 刷新仓库信息；after 在信息读取完成后执行，供检查/更新结束后同步远程版本
    _refreshInfo(after) {
      axios_post("/sys/git_info", {}, (ret) => {
        if (!ret || ret.code !== 0) {
          $("#git_panel_commit").text("—").removeAttr("title");
          $("#git_panel_branch").text("—");
          $("#git_panel_commit_time").text("—");
          $("#git_panel_commit_msg").text("无法读取 Git 信息").removeAttr("title");
          this._isDocker = false;
          this._renderNotice();
          if (!this._running && !this._checking) {
            this._setStatus("无法读取 Git 仓库信息", "danger");
          }
          this._syncButtons();
          if (after) {
            after(null);
          }
          return;
        }
        this._isDocker = !!ret.is_docker;
        this._dirty = !!ret.dirty;
        $("#git_panel_commit")
          .text(ret.short_commit || "—")
          .attr("title", ret.commit || "");
        $("#git_panel_branch").text(ret.branch || "—");
        $("#git_panel_commit_time").text(ret.commit_time || "—");
        $("#git_panel_commit_msg")
          .text(ret.commit_msg || "—")
          .attr("title", ret.commit_msg || "");
        this._renderNotice();
        this._syncButtons();
        if (after) {
          after(ret);
        }
      }, false);
    }

    _renderCommitEmpty(kind, text) {
      const icons = {
        idle: "ti-list-check",
        success: "ti-circle-check",
        danger: "ti-alert-triangle"
      };
      $("#git_panel_commit_list").html(
        `<li class="update-commit-empty is-${kind}">
           <i class="ti ${icons[kind] || icons.idle}"></i>
           <span>${this._escape(text)}</span>
         </li>`
      );
    }

    _renderSkeleton() {
      const rows = [];
      for (let i = 0; i < 3; i++) {
        rows.push(`<li class="update-commit-skeleton">
            <span class="update-skeleton-bar" style="width:62px"></span>
            <span class="update-skeleton-bar" style="flex:1 1 auto"></span>
            <span class="update-skeleton-bar" style="width:66px"></span>
          </li>`);
      }
      $("#git_panel_commit_list").html(rows.join(""));
    }

    _renderChecking() {
      $("#git_panel_remote_ref").text("").removeAttr("title");
      $("#git_panel_remote_hash").text("…").removeAttr("title");
      $("#git_panel_remote_meta").text("正在获取远程分支");
      $("#git_panel_remote_msg").text("正在比较本地与远程提交").removeAttr("title");
      $("#git_panel_delta").text("检测中");
      $("#git_panel_commit_count").text("检测中");
      this._renderSkeleton();
    }

    // 后端提交行格式：hash  说明  (作者, 日期)
    _parseCommit(line) {
      const text = String(line || "").trim();
      const match = text.match(/^([0-9a-f]{7,40})\s{2,}(.+)$/);
      if (!match) {
        return {hash: "", subject: text, author: "", date: ""};
      }
      const hash = match[1];
      let subject = match[2];
      let author = "";
      let date = "";
      const meta = subject.match(/\s{2,}\((.*)\)$/);
      if (meta) {
        subject = subject.slice(0, meta.index).trim();
        const parts = meta[1].split(", ");
        if (parts.length >= 2) {
          date = parts.pop();
          author = parts.join(", ");
        } else {
          author = meta[1];
        }
      }
      return {hash: hash, subject: subject, author: author, date: date};
    }

    _renderUpdate(ret) {
      const commits = (ret.commits || []).map((line) => this._parseCommit(line));
      const behind = Number(ret.behind) || commits.length;
      this._behind = behind;
      const first = commits[0] || {};
      $("#git_panel_remote_ref")
        .text(ret.upstream || "")
        .attr("title", ret.upstream || "");
      $("#git_panel_remote_hash")
        .text(first.hash || "—")
        .attr("title", first.hash || "");
      $("#git_panel_remote_meta").text(first.date || "远程最新提交");
      $("#git_panel_remote_msg")
        .text(first.subject || "远程分支有新的提交")
        .attr("title", first.subject || "");
      $("#git_panel_delta").text(`${behind} 个新提交`);
      $("#git_panel_commit_count").text(`${behind} 个新提交`);

      if (!commits.length) {
        this._renderCommitEmpty("idle", "远程有新提交，但没有返回提交列表");
        return;
      }

      const rows = commits.map((item) => {
        return `<li class="update-commit-item">
            <span class="update-commit-hash" title="${this._escape(item.hash)}">${this._escape(item.hash || "—")}</span>
            <span class="update-commit-subject" title="${this._escape(item.subject)}">${this._escape(item.subject || "（无提交说明）")}</span>
            <span class="update-commit-date" title="${this._escape(item.author)}">${this._escape(item.date || "")}</span>
          </li>`;
      });
      if (commits.length < behind) {
        rows.push(`<li class="update-commit-empty">仅显示最近 ${commits.length} 个提交</li>`);
      }
      $("#git_panel_commit_list").html(rows.join(""));
    }

    _renderLatest(info) {
      const hash = info && info.short_commit ? info.short_commit : "—";
      const msg = info && info.commit_msg ? info.commit_msg : "远程没有新的提交";
      $("#git_panel_remote_ref").text("").removeAttr("title");
      $("#git_panel_remote_hash")
        .text(hash)
        .attr("title", info && info.commit ? info.commit : "");
      $("#git_panel_remote_meta").text("与当前版本相同");
      $("#git_panel_remote_msg").text(msg).attr("title", msg);
      $("#git_panel_delta").text("已最新");
      $("#git_panel_commit_count").text("无新提交");
      this._renderCommitEmpty("success", "当前已是最新版本，无需更新");
    }

    // 更新成功：保留刚拉取的提交列表，标明已应用，而不是回到“无需更新”
    _renderApplied(info) {
      const hash = info && info.short_commit ? info.short_commit : "—";
      const msg = info && info.commit_msg ? info.commit_msg : "";
      $("#git_panel_remote_ref").text("").removeAttr("title");
      $("#git_panel_remote_hash")
        .text(hash)
        .attr("title", info && info.commit ? info.commit : "");
      $("#git_panel_remote_meta").text("已合并到当前版本");
      $("#git_panel_remote_msg").text(msg).attr("title", msg);
      $("#git_panel_delta").text("已更新");
      $("#git_panel_commit_count").text(
        this._behind > 0 ? `已更新 ${this._behind} 个提交` : "已更新"
      );
    }

    _checkFailed(msg) {
      this._checking = false;
      this._hasUpdate = false;
      $("#git_panel_remote_hash").text("—").removeAttr("title");
      $("#git_panel_remote_meta").text("检测失败");
      $("#git_panel_remote_msg").text("请展开更新日志查看原因").removeAttr("title");
      $("#git_panel_delta").text("检测失败");
      $("#git_panel_commit_count").text("检测失败");
      this._renderCommitEmpty("danger", "检测失败，请展开更新日志查看原因");
      const content = $("#git_panel_log_content");
      if (content.find(".update-log-empty").length) {
        content.html(
          `<div class="update-log-empty">检测失败：${this._escape(msg)}</div>`
        );
      }
      this._setState("error");
      this._setStatus(`检测失败：${msg}`, "danger");
      this._expandLog(true);
      this._syncButtons();
    }

    // 检查远程是否有更新（只 fetch，不修改本地代码）
    _checkUpdate() {
      if (this._running || this._checking) {
        return;
      }
      this._checking = true;
      this._hasUpdate = false;
      this._ahead = 0;
      this._setState("checking");
      this._renderChecking();
      this._setStatus("正在检测更新…", "info");
      this._expandLog(false);
      this._resetLog("正在检测更新…");
      this._syncButtons();

      axios_post("/sys/git_check", {}, (ret) => {
        this._checking = false;
        if (ret && ret.logs && ret.logs.length) {
          this._renderLogs(ret.logs);
        } else {
          $("#git_panel_log_content").html(
            '<div class="update-log-empty">检测完成，没有过程日志</div>'
          );
        }

        if (!ret || ret.code !== 0) {
          this._checkFailed((ret && ret.msg) || "未知错误");
          return;
        }

        this._hasUpdate = !!ret.has_update;
        this._ahead = Number(ret.ahead) || 0;
        if (this._hasUpdate) {
          this._setState("update");
          this._renderUpdate(ret);
          this._setStatus(`发现 ${ret.behind} 个新提交`, "info");
        } else {
          this._setState("latest");
          this._setStatus("没有更新内容，当前已是最新版本", "success");
        }
        this._renderNotice();
        this._syncButtons();
        this._refreshInfo((info) => {
          if (!this._hasUpdate) {
            this._renderLatest(info);
          }
        });
      }, false).catch(() => {
        if (this._checking) {
          this._checkFailed("无法连接服务");
        }
      }).finally(() => {
        this._checking = false;
        this._syncButtons();
      });
    }

    // 开始更新：POST 获取 SSE 流，日志和结果在同一个响应里按顺序返回
    _startUpdate() {
      if (this._running || this._checking || !this._hasUpdate || !this._isDocker) {
        return;
      }
      this._running = true;
      this._needsRestart = false;
      this._needsReload = false;
      this._setState("updating");
      this._syncButtons();
      this._abortStream();

      this._setStatus("正在更新，请勿关闭页面", "info");
      this._expandLog(true);
      this._resetLog("正在启动更新…");
      this._setProgress(0, true);
      $("#git_panel_commit_count").text("正在更新");

      this._abort = new AbortController();
      fetch("stream-update-system", {
        method: "POST",
        credentials: "same-origin",
        headers: {"Content-Type": "application/json"},
        body: "{}",
        signal: this._abort.signal
      }).then((response) => {
        if (!response.ok || !response.body) {
          throw new Error("HTTP " + response.status);
        }
        const reader = response.body.getReader();
        const decoder = new TextDecoder("utf-8");
        let buffer = "";

        const pump = () => {
          return reader.read().then((result) => {
            if (result.done) {
              return;
            }
            buffer += decoder.decode(result.value, {stream: true});
            let idx;
            // 解析 SSE 帧：data: {...}\n\n
            while ((idx = buffer.indexOf("\n\n")) >= 0) {
              const frame = buffer.slice(0, idx);
              buffer = buffer.slice(idx + 2);
              const data = frame.split("\n")
                .filter((line) => line.startsWith("data:"))
                .map((line) => line.slice(5).trim())
                .join("\n");
              if (!data) {
                continue;
              }
              let event;
              try {
                event = JSON.parse(data);
              } catch (e) {
                console.error("更新事件解析失败:", data);
                continue;
              }
              this._handleEvent(event);
            }
            return pump();
          });
        };
        return pump();
      }).catch((err) => {
        if (err && err.name === "AbortError") {
          return;
        }
        // 已经收到 done 并结束的不再覆盖结果
        if (!this._abort) {
          return;
        }
        this._finish({code: -1, msg: "更新连接异常：" + (err && err.message ? err.message : err)});
      });
    }

    // 中断进行中的更新流并丢弃缓冲
    _abortStream() {
      if (this._abort) {
        const abort = this._abort;
        this._abort = null;
        abort.abort();
      }
    }

    _handleEvent(event) {
      if (!event || !event.type) {
        return;
      }
      if (event.type === "logs") {
        this._renderLogs(event.records);
      } else if (event.type === "progress") {
        const value = Number(event.value) || 0;
        this._setProgress(value, true);
        if (event.text) {
          this._setStatus(event.text, "info");
        }
      } else if (event.type === "done") {
        this._finish(event.result || {code: -1, msg: "更新未返回结果"});
      }
    }

    _renderLogs(records) {
      if (!records) {
        return;
      }
      if (!Array.isArray(records)) {
        records = [records];
      }
      for (const record of records) {
        if (record) {
          this._pendingLogs.push(record);
        }
      }
      if (this._pendingLogs.length && !this._flushTimer) {
        this._flushTimer = requestAnimationFrame(() => this._flushLogs());
      }
    }

    _flushLogs() {
      this._flushTimer = null;
      if (!this._pendingLogs.length) {
        return;
      }
      const records = this._pendingLogs;
      this._pendingLogs = [];

      const content = $("#git_panel_log_content");
      const scrollEl = document.getElementById("git_panel_log_scroll");
      const atBottom = scrollEl
        ? (scrollEl.scrollTop + scrollEl.clientHeight >= scrollEl.scrollHeight - 30)
        : true;

      content.find(".update-log-empty").remove();
      content.append(records.map((record) => this._buildRow(record)).join(""));

      const lines = content.children(".update-log-line");
      if (lines.length > MAX_LOG_ROWS) {
        lines.slice(0, lines.length - MAX_LOG_ROWS).remove();
      }

      if (atBottom && scrollEl) {
        scrollEl.scrollTop = scrollEl.scrollHeight;
      }
    }

    _buildRow(record) {
      const level = record.level || "INFO";
      let cls = "";
      let tag = "";
      if (level === "WARN") {
        cls = " is-warn";
        tag = '<span class="update-log-level">警告</span>';
      } else if (level === "ERROR") {
        cls = " is-error";
        tag = '<span class="update-log-level">错误</span>';
      } else if (level === "DEBUG") {
        cls = " is-muted";
      }
      return `<div class="update-log-line${cls}">
                <span class="update-log-time">${this._escape(record.time || "")}</span>
                ${tag}
                <span class="update-log-text">${this._escape(record.text || "")}</span>
              </div>`;
    }

    _escape(text) {
      return String(text)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");
    }

    _finish(result) {
      const ret = result || {};
      const ok = ret.code === 0;
      const updated = !!ret.updated;
      this._running = false;
      this._checking = false;
      if (ok) {
        this._hasUpdate = false;
      }
      this._abort = null;
      // 只有前端文件变化时刷新页面即可，其余改动需要重启进程
      this._needsRestart = ok && updated && !ret.frontend_only;
      this._needsReload = ok && updated && !!ret.frontend_only;
      this._syncButtons();

      // 先把还在缓冲的日志写完，再展示结果
      if (this._flushTimer) {
        cancelAnimationFrame(this._flushTimer);
        this._flushTimer = null;
      }
      this._flushLogs();

      if (!ok) {
        this._setState("error");
        this._setStatus(ret.msg || "更新失败，请查看日志", "danger");
        if (this._hasUpdate) {
          $("#git_panel_commit_count").text(`${this._behind} 个新提交`);
        }
        this._expandLog(true);
        this._refreshInfo();
        return;
      }

      this._setProgress(100, true);
      this._setState(updated ? "done" : "latest");
      if (!updated) {
        this._setStatus("当前已是最新版本", "success");
      } else if (this._needsReload) {
        this._setStatus("前端文件已更新，刷新页面生效", "success");
      } else {
        this._setStatus("更新完成，重启后生效", "success");
      }
      this._refreshInfo((info) => {
        if (updated) {
          this._renderApplied(info);
        } else {
          this._renderLatest(info);
        }
      });
    }

    _restart() {
      show_confirm_modal("重启系统以应用更新？", () => {
        // 先关闭更新面板，否则它和等待框的 z-index 相同、又在 DOM 后面，会盖住转圈动画
        $("#modal-git-update").modal("hide");
        restart_system_and_wait();
      });
    }
  }

  if (!customElements.get("update-panel")) {
    customElements.define("update-panel", UpdatePanel);
  }
})();
