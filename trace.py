import os
import sys
import socket
import struct
import time
import json
import urllib.request

def get_ip_info(ip):
    if ip.startswith("10.") or ip.startswith("192.168.") or ip.startswith("172."):
        return "局域网内网"
    try:
        # 使用 ip-api 免费接口查询 AS 号和地理位置
        url = f"http://ip-api.com{ip}?fields=status,country,regionName,city,isp,as"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=3) as response:
            data = json.loads(response.read().decode())
            if data.get("status") == "success":
                return f"[{data.get('country')}-{data.get('city')}] {data.get('isp')} ({data.get('as')})"
    except:
        pass
    return "未知节点"

def traceroute(dest_host, max_hops=30, timeout=2):
    try:
        dest_ip = socket.gethostbyname(dest_host)
    except socket.gaierror:
        print(f"❌ 错误: 无法解析目标主机: {dest_host}")
        return

    print(f"\n=======================================================")
    print(f"🚀 开始测试回程路由: 从 VPS -> {dest_host} ({dest_ip})")
    print(f"=======================================================\n")

    port = 33434
    icmp = socket.getprotobyname('icmp')
    udp = socket.getprotobyname('udp')

    for ttl in range(1, max_hops + 1):
        recv_socket = socket.socket(socket.AF_INET, socket.SOCK_RAW, icmp)
        send_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, udp)
        recv_socket.setsockopt(socket.SOL_IP, socket.IP_TTL, ttl)
        
        recv_socket.bind(("", port))
        send_socket.sendto(b"", (dest_ip, port))
        
        curr_addr = None
        started_time = time.time()
        
        try:
            recv_socket.settimeout(timeout)
            _, curr_addr = recv_socket.recvfrom(512)
            curr_addr = curr_addr[0]
        except socket.timeout:
            pass
        finally:
            send_socket.close()
            recv_socket.close()

        if curr_addr:
            time_spent = round((time.time() - started_time) * 1000, 1)
            info = get_ip_info(curr_addr)
            print(f" {ttl:<2}  {curr_addr:<15}  {time_spent:<6} ms  {info}")
            if curr_addr == dest_ip:
                print("\n🎉 成功到达目的地！")
                break
        else:
            print(f" {ttl:<2}  * * *           超时无响应")

if __name__ == "__main__":
    # 检查是否传入了目标 IP 参数
    if len(sys.argv) < 2:
        print("❌ 错误：缺少目标 IP 参数！")
        print("💡 正确用法: sudo python3 <(curl -fsSL 你的链接) 你的家用公网IP")
        sys.exit(1)
        
    target = sys.argv[1]
    
    # 检查是否拥有 root 权限（Raw Socket 必须）
    if os.getuid() != 0:
        print("❌ 错误：路由追踪需要 root 权限，请在命令前加上 sudo")
        sys.exit(1)
        
    traceroute(target)
