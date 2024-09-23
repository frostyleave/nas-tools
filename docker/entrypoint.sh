#!/bin/sh

cd ${WORKDIR}

# 自动更新
if [ "${NASTOOL_AUTO_UPDATE}" = "true" ]; then
    if [ ! -s /tmp/requirements.txt.sha256sum ]; then
        sha256sum requirements.txt > /tmp/requirements.txt.sha256sum
    fi
    if [ ! -s /tmp/package_list.txt.sha256sum ]; then
        sha256sum package_list.txt > /tmp/package_list.txt.sha256sum
    fi
    echo "更新主程序..."
    git remote set-url origin "${REPO_URL}" &> /dev/null
    echo "windows/" > .gitignore
    # 更新分支
    if [ "${NASTOOL_VERSION}" == "dev" ]; then
      branch="dev"
    else
      branch="master"
    fi

    git clean -dffx
    git fetch --depth 1 origin ${branch}
    git reset --hard origin/${branch}

    if [ $? -eq 0 ]; then
        echo "主程序更新成功"
        # 系统软件包更新
        hash_old=$(cat /tmp/package_list.txt.sha256sum)
        hash_new=$(sha256sum package_list.txt)
        if [ "${hash_old}" != "${hash_new}" ]; then
            echo "检测到package_list.txt有变化，更新软件包..."
            if [ "${NASTOOL_CN_UPDATE}" = "true" ]; then
                sed -i "s/deb.debian.org/${DEBIAN_MIRROR}/g" /etc/apt/sources.list
                apt-get update -y
                if [ $? -ne 0 ]; then
                    echo "无法更新软件包，请更新镜像！"
                fi
            fi
            apt-get install -y $(cat package_list.txt)
            if [ $? -ne 0 ]; then
                echo "无法更新软件包，请更新镜像！"
            else
                echo "软件包安装成功"
                sha256sum package_list.txt > /tmp/package_list.txt.sha256sum
            fi
        fi
        # Python依赖包更新
        hash_old=$(cat /tmp/requirements.txt.sha256sum)
        hash_new=$(sha256sum requirements.txt)
        if [ "${hash_old}" != "${hash_new}" ]; then
            echo "检测到requirements.txt有变化，重新安装依赖..."
            if [ "${NASTOOL_CN_UPDATE}" = "true" ]; then
                pip install --upgrade pip setuptools wheel -i "${PYPI_MIRROR}"
                pip install -r requirements.txt -i "${PYPI_MIRROR}"
            else
                pip install --upgrade pip setuptools wheel
                pip install -r requirements.txt
            fi
            if [ $? -ne 0 ]; then
                echo "无法安装依赖，请更新镜像！"
                exit 1
            else
                echo "依赖安装成功"
                sha256sum requirements.txt > /tmp/requirements.txt.sha256sum
            fi
        fi
    else
        echo "更新失败，继续使用旧的程序来启动..."
    fi
else
    echo "程序自动升级已关闭，如需自动升级请在创建容器时设置环境变量：NASTOOL_AUTO_UPDATE=true"
fi

echo "以PUID=${PUID}，PGID=${PGID}的身份启动程序..."

# 更改 nt userid 和 groupid
groupmod -o -g "$PGID" nt
usermod -o -u "$PUID" nt

# 创建目录、权限设置
chown -R nt:nt "${WORKDIR}"  /etc/hosts /tmp /ms-playwright
# export PATH=${PATH}:/usr/lib/chromium
# gosu nt:nt playwright install chromium
# 执行扩展脚本
exec "$@"

# 掩码设置
umask "${UMASK}"

# 启动主程序
exec gosu nt:nt dumb-init python3 run.py -n NAStool