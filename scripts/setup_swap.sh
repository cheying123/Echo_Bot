#!/bin/bash
# 1GB 服务器优化：添加 2GB swap + 内存参数调优
# 在服务器上执行: bash scripts/setup_swap.sh

set -e

echo "=== 创建 swap（2GB）==="
if [ ! -f /swapfile ]; then
    fallocate -l 2G /swapfile
    chmod 600 /swapfile
    mkswap /swapfile
    swapon /swapfile
    echo '/swapfile none swap sw 0 0' >> /etc/fstab
    echo "Swap 已创建并启用"
else
    echo "Swap 已存在"
fi

echo "=== 当前内存 ==="
free -h

echo "=== 优化系统内存参数 ==="
echo "vm.swappiness=10" >> /etc/sysctl.conf
echo "vm.vfs_cache_pressure=50" >> /etc/sysctl.conf
sysctl -p

echo "=== 完成 ==="
