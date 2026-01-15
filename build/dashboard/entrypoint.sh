#!/bin/bash
export HOST_IP=$(ip -4 addr show | grep -v '127.0.0.1' | grep 'inet' | head -n 1 | awk '{print $2}' | cut -d/ -f1)

# Test docker access
echo "Testing Docker access..."
docker ps > /dev/null 2>&1
if [ $? -eq 0 ]; then
    echo "Docker access: OK"
else
    echo "Docker access: FAILED - logs feature may not work"
fi

exec python3 /app/mining_status.py