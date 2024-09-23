FROM python:3.10-slim AS Builder

# 安装构建依赖和运行所需的依赖包
RUN apt-get update -y \
     && apt-get upgrade -y \
     && apt-get install -y build-essential \
     && apt-get install -y --no-install-recommends \
        gosu \
        bash \
        busybox \
        dumb-init \
        gcc \
        libffi-dev \
        libxml2-dev \
        libxslt-dev \
        musl-dev \
        curl \
        git \
        unzip \
        wget \
        gnupg \
        libnss3 \
        libxss1 \
        libasound2 \
        libxshmfence1 \
        libxrandr2 \
        libxcomposite1 \
        libxdamage1 \
        libfontconfig1 \
        libgbm1 \
        libgtk-3-0 \
        libdrm2 \
        ca-certificates \
        fonts-liberation \
        libappindicator3-1 \
        libx11-xcb1 \
        xdg-utils \
    && \
    if [ "$(uname -m)" = "x86_64" ]; \
        then ln -s /usr/lib/x86_64-linux-musl/libc.so /lib/libc.musl-x86_64.so.1; \
    elif [ "$(uname -m)" = "aarch64" ]; \
        then ln -s /usr/lib/aarch64-linux-musl/libc.so /lib/libc.musl-aarch64.so.1; \
    fi \
    && curl https://rclone.org/install.sh | bash \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# 设置环境变量，将浏览器安装到 /ms-playwright
RUN mkdir -p /ms-playwright
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

# 升级 pip、setuptools、 wheel, 
RUN pip install --upgrade pip setuptools==70.1.1 wheel \
    && pip install cython \
    && pip install --no-cache-dir playwright \
    && python -m playwright install chromium \
    && pip install -r https://raw.githubusercontent.com/frostyleave/nas-tools/dev/requirements.txt \
    && apt-get remove -y build-essential \
    && apt-get autoremove -y \
    && apt-get clean -y \
    && rm -rf \
        /tmp/* \
        /var/lib/apt/lists/* \
        /var/tmp/* \
        /root/.cache

# 复制 rootfs
COPY --chmod=755 ./rootfs /

FROM scratch AS APP

# 从 Builder 阶段复制文件
COPY --from=Builder / /

# 设置环境变量
ENV S6_SERVICES_GRACETIME=30000 \
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
    NASTOOL_VERSION=dev \
    PS1="\u@\h:\w \$ " \
    REPO_URL="https://github.com/frostyleave/nas-tools.git" \
    PYPI_MIRROR="https://pypi.tuna.tsinghua.edu.cn/simple" \
    DEBIAN_MIRROR="http://deb.debian.org/debian/" \
    PUID=0 \
    PGID=0 \
    UMASK=000 \
    WORKDIR="/nas-tools"

WORKDIR ${WORKDIR}

# 创建用户和组
RUN mkdir ${HOME} \
    && addgroup --gid 911 nt \
    && adduser --uid 911 --gid 911 --home ${HOME} --shell /bin/bash --disabled-password nt \
    && python_ver=$(python3 -V | awk '{print $2}') \
    && echo "${WORKDIR}/" > /usr/local/lib/python${python_ver%.*}/site-packages/nas-tools.pth \
    && echo 'fs.inotify.max_user_watches=5242880' >> /etc/sysctl.conf \
    && echo 'fs.inotify.max_user_instances=5242880' >> /etc/sysctl.conf \
    && echo "nt ALL=(ALL) NOPASSWD: ALL" >> /etc/sudoers \
    && git config --global pull.ff only \
    && git clone -b dev ${REPO_URL} ${WORKDIR} --depth=1 --recurse-submodule \
    && git config --global --add safe.directory ${WORKDIR} \
    && cp -f /nas-tools/docker/entrypoint.sh /entrypoint.sh \
    && chmod +x /entrypoint.sh

EXPOSE 3000
VOLUME ["/config"]
ENTRYPOINT ["/entrypoint.sh"]