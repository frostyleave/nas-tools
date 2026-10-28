#!/bin/sh

cd ${WORKDIR}

echo "以PUID=${PUID}，PGID=${PGID}的身份启动程序..."

# 更改 nt userid 和 groupid
groupmod -o -g "$PGID" nt
usermod -o -u "$PUID" nt

# 创建目录、权限设置
chown -R nt:nt "${WORKDIR}"  /etc/hosts /tmp
# export PATH=${PATH}:/usr/lib/chromium
# 执行扩展脚本
exec "$@"

# 掩码设置
umask "${UMASK}"

# 启动主程序
exec dumb-init gosu nt:nt python3 run.py -n NAStool