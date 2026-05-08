


import requests

try:
    # 如果没有安装 requests 库，执行前请先运行: pip install requests
    ip = requests.get('https://api.ip.sb/ip', timeout=10).text.strip()
    print(f"当前出口 IP 地址为: {ip}")
except Exception as e:
    print(f"获取 IP 失败，请检查网络连接: {e}")

    