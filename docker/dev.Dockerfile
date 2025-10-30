#-------------------------------------------------------------------
# 阶段 1: 'builder' - 用于构建所有依赖和产物
#-------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS builder

# 设置环境变量
ENV DEBIAN_FRONTEND=noninteractive \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    WORKDIR="/nas-tools" \
    BRANCH=dev_fastapi \
    REPO_URL="https://github.com/frostyleave/nas-tools.git"

# 允许在构建时覆盖 BRANCH
ARG BRANCH

# 定义构建时和运行时的 apt 依赖
# 构建依赖 (BUILD_DEPS) 将不会进入最终镜像
ENV BUILD_DEPS="build-essential gcc libffi-dev libxml2-dev libxslt-dev musl-dev unzip curl" \
    # 运行时依赖
    RUNTIME_DEPS="bash gosu dumb-init ca-certificates libnss3 libxss1 libasound2 libxshmfence1 libxcomposite1 libxdamage1 libxrandr2 libfontconfig1 libgbm1 libdrm2 libx11-xcb1 libgtk-3-0 libappindicator3-1 git"

# 安装所有依赖
RUN apt-get update -y \
     && apt-get install -y --no-install-recommends \
        $BUILD_DEPS \
        $RUNTIME_DEPS \
    && \
    # 设置 musl 符号链接
    if [ "$(uname -m)" = "x86_64" ]; \
        then ln -s /usr/lib/x86_64-linux-musl/libc.so /lib/libc.musl-x86_64.so.1; \
    elif [ "$(uname -m)" = "aarch64" ]; \
        then ln -s /usr/lib/aarch64-linux-musl/libc.so /lib/libc.musl-aarch64.so.1; \
    fi \
    # 安装 rclone
    && curl https://rclone.org/install.sh | bash \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR ${WORKDIR}

# 1. 先克隆代码
RUN git config --global pull.ff only \
    && git clone -b ${BRANCH} ${REPO_URL} ${WORKDIR} --depth=1 --recurse-submodule \
    && git config --global --add safe.directory ${WORKDIR}

# 2. 再安装 Python 依赖 (使用本地文件)
RUN mkdir -p ${PLAYWRIGHT_BROWSERS_PATH} \
    && pip install --no-cache-dir --upgrade pip setuptools==70.1.1 wheel \
    && pip install --no-cache-dir cython \
    && pip install --no-cache-dir playwright \
    && python -m playwright install chromium \
    && pip install --no-cache-dir -r ${WORKDIR}/requirements.txt \
    && rm -rf /root/.cache

# 复制 rootfs (builder 阶段也需要，因为 final 阶段会从中复制)
COPY --chmod=755 ./rootfs /


#-------------------------------------------------------------------
# 阶段 2: 'final' - 最终的轻量级运行时镜像
#-------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS final

# 重新声明 ARG，以便在 ENV 中使用
ARG BRANCH=dev_fastapi

# 设置环境变量 (这里不需要 REPO_URL，因为 clone 已在 builder 阶段完成)
ENV DEBIAN_FRONTEND=noninteractive \
    S6_SERVICES_GRACETIME=30000 \
    S6_KILL_GRACETIME=60000 \
    S6_CMD_WAIT_FOR_SERVICES_MAXTIME=0 \
    S6_SYNC_DISKS=1 \
    HOME="/nt" \
    TERM="xterm" \
    PATH=${PATH}:/usr/lib/chromium \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    LANG="C.UTF-8" \
    TZ="Asia/Shanghai" \
    NASTOOL_CONFIG="/config/config.yaml" \
    NASTOOL_AUTO_UPDATE=false \
    NASTOOL_CN_UPDATE=false \
    NASTOOL_VERSION=${BRANCH} \
    PS1="\u@\h:\w \$ " \
    PUID=0 \
    PGID=0 \
    UMASK=000 \
    WORKDIR="/nas-tools"

# 定义运行时 apt 依赖 (必须与 builder 阶段的 RUNTIME_DEPS 一致)
ENV RUNTIME_DEPS="bash gosu dumb-init ca-certificates libnss3 libxss1 libasound2 libxshmfence1 libxcomposite1 libxdamage1 libxrandr2 libfontconfig1 libgbm1 libdrm2 libx11-xcb1 libgtk-3-0 libappindicator3-1 git"

# 只安装运行时依赖
RUN apt-get update -y \
     && apt-get install -y --no-install-recommends \
        $RUNTIME_DEPS \
    # 清理
    && apt-get clean -y \
    && rm -rf \
        /tmp/* \
        /var/lib/apt/lists/* \
        /var/tmp/* \
        /root/.cache

WORKDIR ${WORKDIR}

# 从 builder 阶段精确复制产物
COPY --from=builder /usr/local/lib/ /usr/local/lib/
COPY --from=builder /usr/local/bin/ /usr/local/bin/
COPY --from=builder ${PLAYWRIGHT_BROWSERS_PATH} ${PLAYWRIGHT_BROWSERS_PATH}
COPY --from=builder ${WORKDIR} ${WORKDIR}

COPY --chmod=755 ./rootfs /

# 创建用户和配置
RUN mkdir ${HOME} \
    && addgroup --gid 911 nt \
    && adduser --uid 911 --gid 911 --home ${HOME} --shell /bin/bash --disabled-password nt \
    && python_ver=$(python3 -V | awk '{print $2}') \
    && echo "${WORKDIR}/" > /usr/local/lib/python${python_ver%.*}/site-packages/nas-tools.pth \
    && echo 'fs.inotify.max_user_watches=5242880' >> /etc/sysctl.conf \
    && echo 'fs.inotify.max_user_instances=5242880' >> /etc/sysctl.conf \
    && echo "nt ALL=(ALL) NOPASSWD: ALL" >> /etc/sudoers \
    && cp -f ${WORKDIR}/docker/entrypoint.sh /entrypoint.sh \
    && chmod +x /entrypoint.sh

EXPOSE 3000
VOLUME ["/config"]
ENTRYPOINT ["/entrypoint.sh"]