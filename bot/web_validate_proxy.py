import sys
import json

TEST_URLS = [
    "http://httpbin.org/ip",
    "http://ip-api.com/json",
    "http://ifconfig.me/ip",
]


def parse_proxy(raw):
    raw = raw.strip()
    if raw.startswith("http://") or raw.startswith("https://") or \
       raw.startswith("socks5://") or raw.startswith("socks4://"):
        return raw
    parts = raw.split(":")
    if len(parts) == 2:
        host, port = parts
        if port.isdigit():
            return f"http://{host}:{port}"
    elif len(parts) == 4:
        host, port, user, pwd = parts
        if port.isdigit():
            return f"http://{user}:{pwd}@{host}:{port}"
    return None


def validate_format(raw):
    raw = raw.strip()
    if not raw:
        return False, "Empty proxy"
    parsed = parse_proxy(raw)
    if not parsed:
        return False, "Invalid format. Use: ip:port, ip:port:user:pass, http://ip:port, socks5://ip:port"
    return True, parsed


def live_test_requests(proxy_url: str, timeout: int = 10) -> dict:
    """Test proxy using requests library (strict enforcement — won't fall back to direct)."""
    try:
        import requests
        from requests.exceptions import ProxyError, ConnectTimeout, ReadTimeout, ConnectionError as ReqConnectionError
        proxies = {"http": proxy_url, "https": proxy_url}
        for url in TEST_URLS:
            try:
                resp = requests.get(
                    url,
                    proxies=proxies,
                    timeout=timeout,
                    allow_redirects=False,
                    headers={"User-Agent": "Mozilla/5.0"},
                )
                if resp.status_code == 200:
                    try:
                        data = resp.json()
                        ip = data.get("origin") or data.get("query") or data.get("ip") or ""
                    except Exception:
                        ip = resp.text.strip()[:50]
                    return {"ok": True, "ip": ip}
                # Non-200 from test URL — proxy responded but URL issue; try next
                continue
            except ProxyError as e:
                return {"ok": False, "error": f"Proxy refused: {str(e)[:100]}"}
            except (ConnectTimeout, ReqConnectionError) as e:
                return {"ok": False, "error": f"Could not connect to proxy: {str(e)[:100]}"}
            except ReadTimeout:
                return {"ok": False, "error": "Proxy connected but response timed out"}
            except Exception as e:
                return {"ok": False, "error": str(e)[:100]}
        return {"ok": False, "error": "All test URLs returned non-200"}
    except ImportError:
        return live_test_urllib(proxy_url, timeout)


def live_test_urllib(proxy_url: str, timeout: int = 10) -> dict:
    """Fallback test using urllib — less reliable but available everywhere."""
    import urllib.request
    import urllib.error
    import socket
    for url in TEST_URLS:
        try:
            proxy_handler = urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url})
            opener = urllib.request.build_opener(proxy_handler)
            opener.addheaders = [("User-Agent", "Mozilla/5.0")]
            response = opener.open(url, timeout=timeout)
            raw = response.read()
            if raw:
                try:
                    data = json.loads(raw.decode())
                    ip = data.get("origin") or data.get("query") or data.get("ip") or ""
                except Exception:
                    ip = raw.decode()[:50].strip()
                return {"ok": True, "ip": ip}
        except urllib.error.URLError as e:
            return {"ok": False, "error": f"Connection failed: {str(e.reason)[:120]}"}
        except socket.timeout:
            return {"ok": False, "error": "Connection timed out"}
        except OSError as e:
            return {"ok": False, "error": str(e)[:100]}
        except Exception:
            continue
    return {"ok": False, "error": "All test URLs failed"}


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"valid": False, "tested": False, "error": "No proxy provided"}))
        return

    action = sys.argv[1]

    if action == "validate":
        raw = sys.argv[2] if len(sys.argv) > 2 else ""
        valid, result = validate_format(raw)
        if not valid:
            print(json.dumps({"valid": False, "tested": False, "error": result}))
            return

        proxy_url = result

        if proxy_url.startswith("socks"):
            print(json.dumps({
                "valid": True,
                "proxy": raw,
                "tested": False,
                "message": "SOCKS proxy format valid (live test skipped — SOCKS not supported for validation)",
            }))
            return

        test = live_test_requests(proxy_url, timeout=10)
        if test["ok"]:
            print(json.dumps({
                "valid": True,
                "proxy": raw,
                "tested": True,
                "ip": test.get("ip", ""),
                "message": "Proxy is live and working",
            }))
        else:
            print(json.dumps({
                "valid": True,
                "proxy": raw,
                "tested": False,
                "error": test.get("error", "Connection failed"),
                "message": f"Proxy is dead: {test.get('error', 'Connection failed')}",
            }))

    elif action == "format_check":
        raw = sys.argv[2] if len(sys.argv) > 2 else ""
        valid, result = validate_format(raw)
        print(json.dumps({
            "valid": valid,
            "error": "" if valid else result,
            "proxy": raw if valid else "",
        }))


if __name__ == "__main__":
    main()
