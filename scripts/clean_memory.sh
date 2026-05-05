#!/bin/bash
# 自动清理内存脚本
# 添加到 crontab：*/10 * * * * bash /opt/echo-bot/scripts/clean_memory.sh >> /var/log/clean_memory.log 2>&1

MEM_THRESHOLD=100    # 可用内存低于此值（MB）时触发清理
SWAP_THRESHOLD=500   # swap 使用超过此值（MB）时清理 swap
CONTAINER_NAME="qq-ai-bot"
LOG_FILE="/var/log/clean_memory.log"

now() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')]"
}

# 获取可用内存（MB）
avail_mem=$(free -m | awk '/^Mem:/ {print $7}')
# 获取 swap 使用量（MB）
used_swap=$(free -m | awk '/^Swap:/ {print $3}')

if [ "$avail_mem" -lt "$MEM_THRESHOLD" ]; then
    echo "$(now) 可用内存 ${avail_mem}MB < ${MEM_THRESHOLD}MB，触发清理"

    # 1. 清理 page cache
    sync
    echo 3 > /proc/sys/vm/drop_caches
    echo "  -> 已清理 page cache"

    # 2. 检查 Docker 容器内存
    if command -v docker &> /dev/null; then
        mem_usage=$(docker stats $CONTAINER_NAME --no-stream --format "{{.MemUsage}}" 2>/dev/null | grep -oP '\d+(?=MiB)' || echo 0)
        if [ "$mem_usage" -gt 400 ]; then
            echo "  -> 容器内存使用 ${mem_usage}MB，重启容器"
            docker restart $CONTAINER_NAME
        fi
    fi

    avail_after=$(free -m | awk '/^Mem:/ {print $7}')
    echo "  -> 清理后可用内存: ${avail_after}MB"
fi

if [ "$used_swap" -gt "$SWAP_THRESHOLD" ]; then
    echo "$(now) Swap 使用 ${used_swap}MB > ${SWAP_THRESHOLD}MB，清理 swap"
    swapoff -a && swapon -a
    echo "  -> Swap 已清理"
fi
