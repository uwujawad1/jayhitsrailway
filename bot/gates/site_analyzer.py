import re
import ssl
import socket
import asyncio
import time
import logging
from urllib.parse import urlparse
from typing import Dict, Any, Optional, Tuple

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger("site_analyzer")

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
REQUEST_TIMEOUT = 12

PAYMENT_GATEWAY_PATTERNS = {
    "Stripe": r"js\.stripe\.com|stripe\.com/v|stripe-api|pk_live_|pk_test_|stripe\.js|stripe_cc|stripejs",
    "PayPal": r"paypal\.com|paypalobjects|paypal\.js|paypal-checkout|ppcp",
    "Braintree": r"braintreegateway\.com|braintree\.js|braintree-web|braintree",
    "Square": r"squareup\.com|square\.js|connect\.squareup\.com|js\.squareup\.com|square_online",
    "Authorize.net": r"authorize\.net|authorizenet|accept\.js",
    "2Checkout": r"2checkout\.com|avangate",
    "Adyen": r"adyen\.com|adyen\.js|adyen",
    "Worldpay": r"worldpay\.com|worldpay",
    "SagePay": r"sagepay\.com|sagepay",
    "Razorpay": r"razorpay\.com|checkout\.razorpay\.com|razorpay",
    "Klarna": r"klarna\.com|klarna\.js|klarna",
    "Amazon Pay": r"pay\.amazon\.com|amazon-payments|amazon_pay",
    "WePay": r"wepay\.com|wepay",
    "PayU": r"payu\.in|payu\.com|payubiz|payu",
    "Mollie": r"mollie\.com|mollie\.js|mollie",
    "Payoneer": r"payoneer\.com|payoneer",
    "Paytm": r"paytm\.com|securegw\.paytm|paytm",
    "Alipay": r"alipay\.com|alipay",
    "Afterpay": r"afterpay\.com|afterpay",
    "Sezzle": r"sezzle\.com|sezzle",
    "Affirm": r"affirm\.com|affirm",
    "Zip": r"zip\.co",
    "Revolut": r"revolut\.com|revolut",
    "Shopify Payments": r"cdn\.shopify\.com|shopify-pay|shopify_payments|shop\.js",
    "PayTrace": r"paytrace\.com|paytrace",
    "Bambora": r"bambora\.com|bambora",
    "PaySimple": r"paysimple\.com|paysimple",
    "CyberSource": r"cybersource\.com|cybersource",
    "Elavon": r"elavon\.com|elavon",
    "Heartland": r"heartland\.us|heartlandpaymentsystems|heartland",
    "BluePay": r"bluepay\.com|bluepay",
    "FirstData": r"firstdata\.com|firstdata",
    "Chase Paymentech": r"chase\.com/payment|paymentech|chase_paymentech",
    "Fiserv": r"fiserv\.com|fiserv",
    "Ingenico": r"ingenico\.com|ingenico",
    "Recurly": r"recurly\.com|recurly\.js|recurly",
    "Spreedly": r"spreedly\.com|spreedly",
    "PayFlow": r"payflow|payflowpro",
    "Skrill": r"skrill\.com|skrill",
    "GoCardless": r"gocardless\.com|gocardless",
    "Dwolla": r"dwolla\.com|dwolla",
    "Wirecard": r"wirecard\.com|wirecard",
    "Clover": r"clover\.com|clover",
    "Paystack": r"paystack\.com|paystack",
    "Moneris": r"moneris\.com|moneris",
    "USAePay": r"usaepay\.com|usaepay",
    "Paysafe": r"paysafe\.com|paysafe",
    "eway": r"eway\.com\.au|eway\.io|eway",
    "Airwallex": r"airwallex\.com|airwallex",
    "Viva Wallet": r"vivawallet\.com|viva_wallet|vivapayments",
    "Trustly": r"trustly\.com|trustly",
    "SumUp": r"sumup\.com|sumup",
    "MercadoPago": r"mercadopago\.com|mercadolibre|mercadopago",
    "QIWI": r"qiwi\.com|qiwi",
    "WooCommerce Payments": r"woocommerce_payments|woocommerce-payments",
    "Payeezy": r"payeezy\.com|payeezy",
    "PayWay": r"payway\.com|payway",
    "QuickBooks Payments": r"quickbooks\.com/payments|quickbooks_payments|intuit.*payment",
    "SecurePay": r"securepay\.com|securepay",
    "Merchant One": r"merchantone\.com|merchant_one",
    "Cognito Forms": r"cognitoforms\.com|cognito\.load|cognito-form|cognitoforms",
    "Donorbox": r"donorbox\.org|donorbox",
    "Give (WP)": r"givewp\.com|give-form|give-donation",
    "Venmo": r"venmo\.com|venmo",
    "Blackbaud": r"blackbaud\.com|blackbaud|bbpayments|bbox",
    "iATS Payments": r"iatspayments\.com|iatspayments",
    "Network for Good": r"networkforgood\.com|networkforgood",
    "Classy": r"classy\.org|classy-pay",
    "Bloomerang": r"bloomerang\.co|bloomerang",
    "NeonCRM": r"neoncrm\.com|neonpay",
    "Kindful": r"kindful\.com|kindful",
    "Qgiv": r"qgiv\.com|qgiv",
    "GiveWP": r"developer\.developer\.developer|give-recurring|give-form-id",
    "Formstack": r"formstack\.com|formstack",
    "JotForm": r"jotform\.com|jotform",
    "Wufoo": r"wufoo\.com|wufoo",
    "Typeform": r"typeform\.com|typeform",
    "Gravity Forms": r"gravityforms|gform_submit|gf_global",
    "Ninja Forms": r"ninja-forms|nf-form",
    "WPForms": r"wpforms\.com|wpforms",
    "Helcim": r"helcim\.com|helcim",
    "CardConnect": r"cardconnect\.com|cardconnect|cardpointe",
    "Flywire": r"flywire\.com|flywire",
    "Cashnet": r"cashnet\.com|cashnet",
    "TouchNet": r"touchnet\.com|touchnet",
    "Windcave": r"windcave\.com|paymentexpress\.com|windcave",
    "Checkout.com": r"checkout\.com/js|checkout\.com/api|cko-sessid",
    "dLocal": r"dlocal\.com|dlocal",
    "Rapyd": r"rapyd\.net|rapyd",
}

FORM_BUILDER_PAYMENT_PATTERNS = {
    "Cognito Forms": r"cognitoforms\.com|cognito\.load\s*\(",
    "Donorbox": r"donorbox\.org",
    "JotForm": r"jotform\.com",
    "Formstack": r"formstack\.com",
    "Gravity Forms": r"gravityforms|gform_submit",
    "WPForms": r"wpforms",
    "Ninja Forms": r"ninja-forms|nf-form",
    "Typeform": r"typeform\.com",
    "Wufoo": r"wufoo\.com",
}

PAYMENT_TEXT_PATTERNS = re.compile(
    r'credit\s*card|debit\s*card|pay\s*(?:with|via|by|using)\s*(?:credit|debit|card|stripe|paypal|venmo)|'
    r'accept(?:s|ing)?\s*(?:credit|debit|card|visa|mastercard|amex|discover)|'
    r'visa.*mastercard|mastercard.*visa|'
    r'donate\s*(?:now|today|online)|make\s*a\s*(?:donation|payment|gift)',
    re.IGNORECASE
)

SECURITY_HEADERS = [
    "Content-Security-Policy",
    "Strict-Transport-Security",
    "X-Frame-Options",
    "X-Content-Type-Options",
    "X-XSS-Protection",
    "Referrer-Policy",
    "Permissions-Policy",
    "Cross-Origin-Opener-Policy",
    "Cross-Origin-Embedder-Policy",
    "Cross-Origin-Resource-Policy",
]

GRAPHQL_PATHS = [
    "/graphql", "/api/graphql", "/v1/graphql", "/query",
    "/api/query", "/graphql-api", "/graphiql",
    "/api/v2/graphql", "/gql", "/_graphql",
]


def validate_url(url: str) -> Tuple[bool, Optional[str], Optional[str]]:
    url = url.strip()
    if not url:
        return False, None, "URL cannot be empty"
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url
    pattern = re.compile(
        r'^https?://'
        r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,20}\.?)'
        r'(?::\d+)?'
        r'(?:/?|[/?]\S+)$', re.IGNORECASE)
    if not pattern.match(url):
        return False, None, "Invalid URL format"
    try:
        parsed = urlparse(url)
        if not parsed.netloc:
            return False, None, "Invalid domain"
        hostname = parsed.hostname or ''
        blocked = ['localhost', '127.0.0.1', '0.0.0.0', '::1']
        if hostname.lower() in blocked:
            return False, None, "Local addresses are not allowed"
        ip_match = re.match(r'^(\d+)\.(\d+)\.(\d+)\.(\d+)$', hostname)
        if ip_match:
            octets = [int(o) for o in ip_match.groups()]
            if octets[0] == 10:
                return False, None, "Private IP addresses are not allowed"
            if octets[0] == 172 and 16 <= octets[1] <= 31:
                return False, None, "Private IP addresses are not allowed"
            if octets[0] == 192 and octets[1] == 168:
                return False, None, "Private IP addresses are not allowed"
            if octets[0] == 169 and octets[1] == 254:
                return False, None, "Link-local addresses are not allowed"
        return True, url, None
    except Exception as e:
        return False, None, str(e)


def _detect_cloudflare(response) -> Dict[str, Any]:
    detected = False
    evidence = []
    cf_headers = ['cf-ray', 'cf-cache-status', 'cf-request-id']
    resp_headers_lower = {k.lower(): v for k, v in response.headers.items()}
    for h in cf_headers:
        if h in resp_headers_lower:
            detected = True
            evidence.append(f"Header: {h}")
    server = resp_headers_lower.get('server', '').lower()
    if 'cloudflare' in server:
        detected = True
        evidence.append(f"Server: cloudflare")
    return {'detected': detected, 'evidence': evidence}


def _detect_captcha(soup, html: str) -> Dict[str, Any]:
    types = []
    html_lower = html.lower()
    if 'recaptcha' in html_lower or 'g-recaptcha' in html_lower:
        types.append('reCAPTCHA')
    if 'hcaptcha' in html_lower or 'h-captcha' in html_lower:
        types.append('hCaptcha')
    if 'cf-turnstile' in html_lower or 'turnstile' in html_lower:
        types.append('Turnstile')
    if 'geetest' in html_lower:
        types.append('GeeTest')
    if 'arkose' in html_lower or 'funcaptcha' in html_lower:
        types.append('Arkose')
    if 'datadome' in html_lower:
        types.append('DataDome')
    if 'perimeterx' in html_lower:
        types.append('PerimeterX')
    return {'detected': len(types) > 0, 'types': types}


def _detect_graphql(soup, html: str) -> Dict[str, Any]:
    html_lower = html.lower()
    if 'graphql' in html_lower or '/graphql' in html_lower:
        return {'detected': True}
    return {'detected': False}


async def _probe_graphql(client, base_url: str) -> Dict[str, Any]:
    parsed = urlparse(base_url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    found = []
    tasks = []
    for path in GRAPHQL_PATHS[:6]:
        tasks.append(_check_graphql_path(client, base + path))
    results = await asyncio.gather(*tasks, return_exceptions=True)
    for i, r in enumerate(results):
        if isinstance(r, str):
            found.append(r)
    return {'detected': len(found) > 0, 'endpoints': found}


async def _check_graphql_path(client, url: str) -> Optional[str]:
    try:
        r = await client.get(url, timeout=5)
        if r.status_code == 200:
            txt = r.text.lower()
            if 'graphql' in txt or '"data"' in txt or '"errors"' in txt:
                return url
    except Exception:
        pass
    return None


def _detect_cms(soup, html: str) -> Dict[str, Any]:
    html_lower = html.lower()
    detected = []
    indicators = {
        'WordPress': ['wp-content', 'wp-includes', 'wp-admin'],
        'Shopify': ['cdn.shopify.com', 'shopify-analytics'],
        'WooCommerce': ['woocommerce', 'wc-ajax'],
        'BigCommerce': ['bigcommerce'],
        'Magento': ['magento', 'mage/'],
        'PrestaShop': ['prestashop'],
        'OpenCart': ['opencart'],
        'Drupal': ['/sites/default/', 'drupal.js'],
        'Drupal Commerce': ['drupal commerce'],
        'Joomla': ['/media/jui/', 'joomla.js'],
        'Squarespace': ['squarespace.com'],
        'Wix': ['wix.com', 'wixstatic'],
        'Webflow': ['webflow.com'],
        'Volusion': ['volusion'],
        '3dcart': ['3dcart'],
        'Shift4Shop': ['shift4shop'],
        'Ecwid': ['ecwid'],
        'Big Cartel': ['big cartel', 'bigcartel'],
        'Weebly': ['weebly'],
        'Salesforce Commerce': ['salesforce commerce cloud', 'demandware'],
        'Zen Cart': ['zen cart', 'zen-cart'],
        'VirtueMart': ['virtuemart'],
        'nopCommerce': ['nopcommerce'],
        'osCommerce': ['oscommerce'],
        'Spree Commerce': ['spree commerce'],
        'Next.js': ['_next/'],
        'React': ['react-dom', '__react'],
        'Vue': ['vue.js', 'vue.min.js'],
    }
    for cms, terms in indicators.items():
        for term in terms:
            if term.lower() in html_lower:
                detected.append(cms)
                break
    meta_gen = soup.find('meta', {'name': 'generator'})
    if meta_gen:
        gen = meta_gen.get('content', '').lower()
        for cms in indicators:
            if cms.lower() in gen and cms not in detected:
                detected.append(cms)
    return {'detected': ', '.join(detected) if detected else 'Unknown', 'types': detected}


def _detect_payment_gateways(soup, html: str) -> Dict[str, Any]:
    detected = set()
    evidence = []
    scripts = soup.find_all('script', src=True)
    for s in scripts:
        src = s.get('src', '') or ''
        for gw, pattern in PAYMENT_GATEWAY_PATTERNS.items():
            if re.search(pattern, src, re.IGNORECASE):
                detected.add(gw)
                evidence.append(f"Script: {gw}")
                break
    inline_scripts = soup.find_all('script', src=False)
    for s in inline_scripts:
        content = s.get_text() or ''
        for gw, pattern in PAYMENT_GATEWAY_PATTERNS.items():
            if gw in detected:
                continue
            if re.search(pattern, content, re.IGNORECASE):
                if not any(t in content.lower() for t in ['font-awesome', 'fas fa-', 'far fa-']):
                    detected.add(gw)
                    evidence.append(f"Inline: {gw}")
                    break
    for gw, pattern in FORM_BUILDER_PAYMENT_PATTERNS.items():
        if gw in detected:
            continue
        for s in inline_scripts:
            content = s.get_text() or ''
            if re.search(pattern, content, re.IGNORECASE):
                detected.add(gw)
                evidence.append(f"FormBuilder: {gw}")
                break
    forms = soup.find_all('form', action=True)
    for form in forms:
        action = form.get('action', '') or ''
        for gw, pattern in PAYMENT_GATEWAY_PATTERNS.items():
            if gw in detected:
                continue
            if re.search(pattern, action, re.IGNORECASE):
                detected.add(gw)
                evidence.append(f"Form: {gw}")
                break
    iframes = soup.find_all('iframe', src=True)
    for iframe in iframes:
        src = iframe.get('src', '') or ''
        for gw, pattern in PAYMENT_GATEWAY_PATTERNS.items():
            if gw in detected:
                continue
            if re.search(pattern, src, re.IGNORECASE):
                detected.add(gw)
                evidence.append(f"Iframe: {gw}")
                break
    link_tags = soup.find_all('link', href=True)
    for link in link_tags:
        href = link.get('href', '') or ''
        for gw, pattern in PAYMENT_GATEWAY_PATTERNS.items():
            if gw in detected:
                continue
            if re.search(pattern, href, re.IGNORECASE):
                detected.add(gw)
                evidence.append(f"Link: {gw}")
                break
    html_lower = html.lower()
    for gw, pattern in PAYMENT_GATEWAY_PATTERNS.items():
        if gw in detected:
            continue
        if re.search(pattern, html_lower):
            detected.add(gw)
            evidence.append(f"HTML: {gw}")
    all_text = soup.get_text(' ', strip=True)
    text_matches = PAYMENT_TEXT_PATTERNS.findall(all_text)
    if text_matches and not detected:
        for match in text_matches[:3]:
            evidence.append(f"Text: \"{match.strip()}\"")
    all_links = soup.find_all('a')
    for a in all_links:
        link_text = (a.get_text() or '').strip().lower()
        href = (a.get('href', '') or '').lower()
        if 'paypal' in link_text or 'paypal' in href:
            if 'PayPal' not in detected:
                detected.add('PayPal')
                evidence.append(f"Link text: PayPal")
        if 'venmo' in link_text or 'venmo' in href:
            if 'Venmo' not in detected:
                detected.add('Venmo')
                evidence.append(f"Link text: Venmo")
        if 'stripe' in link_text or ('stripe' in href and 'pinstripe' not in href):
            if 'Stripe' not in detected:
                detected.add('Stripe')
                evidence.append(f"Link text: Stripe")
    meta_tags = soup.find_all('meta')
    for meta in meta_tags:
        content = (meta.get('content', '') or '')
        for gw, pattern in PAYMENT_GATEWAY_PATTERNS.items():
            if gw in detected:
                continue
            if re.search(pattern, content, re.IGNORECASE):
                detected.add(gw)
                evidence.append(f"Meta: {gw}")
    return {
        'gateways': sorted(list(detected)),
        'count': len(detected),
        'evidence': evidence,
    }


def _detect_checkout(soup, html: str) -> Dict[str, Any]:
    html_lower = html.lower()
    features = {}
    if any(t in html_lower for t in ['add-to-cart', 'add_to_cart', 'addtocart']):
        features['cart'] = True
    if any(t in html_lower for t in ['checkout', 'check-out']):
        features['checkout'] = True
    cc_fields = ['card number', 'cardnumber', 'cc-number', 'credit card', 'card-number',
                 'payment method', 'payment-method', 'payment_method', 'card details',
                 'card information', 'debit card']
    if any(t in html_lower for t in cc_fields):
        features['card_form'] = True
    if any(t in html_lower for t in ['billing', 'billing_address', 'billing-address']):
        features['billing'] = True
    if any(t in html_lower for t in ['order summary', 'order total', 'subtotal']):
        features['order_summary'] = True
    donate_terms = ['donate', 'donation', 'give now', 'give today', 'contribute',
                    'make a gift', 'support us', 'donate now', 'donate today',
                    'donate online', 'giving', 'pledge']
    if any(t in html_lower for t in donate_terms):
        features['donation_form'] = True
    score = (len(features) / 6) * 100 if features else 0
    return {'features': features, 'score': round(score)}


def _analyze_security_headers(response) -> Dict[str, Any]:
    present = []
    missing = []
    resp_headers = {k.lower(): v for k, v in response.headers.items()}
    for h in SECURITY_HEADERS:
        if h.lower() in resp_headers:
            present.append(h)
        else:
            missing.append(h)
    score = (len(present) / len(SECURITY_HEADERS)) * 100 if SECURITY_HEADERS else 0
    return {
        'score': round(score, 1),
        'present': present,
        'missing': missing,
    }


def _analyze_ssl(url: str) -> Dict[str, Any]:
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname or parsed.netloc
        port = parsed.port or 443
        if parsed.scheme != 'https':
            return {'valid': False, 'error': 'Not HTTPS'}
        context = ssl.create_default_context()
        with socket.create_connection((hostname, port), timeout=5) as sock:
            with context.wrap_socket(sock, server_hostname=hostname) as ssock:
                cert = ssock.getpeercert()
                issuer_parts = dict(x[0] for x in cert.get('issuer', []))
                subject_parts = dict(x[0] for x in cert.get('subject', []))
                not_after = cert.get('notAfter', '')
                cipher = ssock.cipher()
                return {
                    'valid': True,
                    'issuer': issuer_parts.get('organizationName', 'Unknown'),
                    'subject': subject_parts.get('commonName', 'Unknown'),
                    'expires': not_after,
                    'protocol': cipher[1] if cipher else 'Unknown',
                    'cipher': cipher[0] if cipher else 'Unknown',
                }
    except ssl.SSLCertVerificationError as e:
        return {'valid': False, 'error': 'Certificate verification failed'}
    except Exception as e:
        return {'valid': False, 'error': str(e)[:60]}


def _detect_waf(response) -> Dict[str, Any]:
    resp_headers_lower = {k.lower(): v for k, v in response.headers.items()}
    waf_indicators = {
        'Sucuri': 'x-sucuri-id',
        'Akamai': 'x-akamai-transformed',
        'Incapsula': 'x-cdn',
        'StackPath': 'x-stackpath-cache',
        'ModSecurity': 'x-modsecurity',
    }
    detected = []
    for name, header in waf_indicators.items():
        if header in resp_headers_lower:
            detected.append(name)
    server = resp_headers_lower.get('server', '').lower()
    if 'sucuri' in server:
        detected.append('Sucuri')
    if 'akamai' in server:
        detected.append('Akamai')
    if 'imperva' in server or 'incapsula' in server:
        detected.append('Imperva')
    return {'detected': list(set(detected))}


PAYMENT_SUBPAGES = [
    '/donate', '/donation', '/donations', '/give', '/giving',
    '/contribute', '/support', '/payment', '/pay', '/checkout',
    '/shop', '/store', '/cart', '/order', '/subscribe',
    '/membership', '/join', '/signup', '/register',
    '/fundraise', '/campaign', '/pledge',
    '/donate.php', '/donation.php', '/checkout.php', '/payment.php',
    '/pay.php', '/give.php', '/shop.php', '/store.php',
    '/donate.html', '/donation.html', '/give.html', '/checkout.html',
]

PAYMENT_LINK_KEYWORDS = re.compile(
    r'donat|give|giving|contribut|support|payment|pay\b|checkout|shop|store|'
    r'cart|order|subscri|member|join|signup|fundrais|campaign|pledge|tithe|offering',
    re.IGNORECASE
)


def _resolve_url(href: str, base_url: str, base_domain: str) -> Optional[str]:
    href = href.strip()
    if not href or href.startswith('#') or href.startswith('mailto:') or href.startswith('tel:') or href.startswith('javascript:'):
        return None
    clean = href.split('?')[0].split('#')[0]
    if not clean:
        return None
    if clean.startswith('http://') or clean.startswith('https://'):
        if clean.startswith(base_domain):
            return clean
        return None
    if clean.startswith('/'):
        return base_domain + clean
    parsed = urlparse(base_url)
    if '/' in parsed.path.lstrip('/'):
        base_dir = base_url.rsplit('/', 1)[0]
    else:
        base_dir = base_domain
    return base_dir + '/' + clean


def _find_payment_links(soup, base_url: str) -> list:
    parsed = urlparse(base_url)
    base_domain = f"{parsed.scheme}://{parsed.netloc}"
    found = set()
    for a in soup.find_all('a', href=True):
        href = a.get('href', '') or ''
        text = (a.get_text() or '').strip().lower()
        if PAYMENT_LINK_KEYWORDS.search(text) or PAYMENT_LINK_KEYWORDS.search(href):
            resolved = _resolve_url(href, base_url, base_domain)
            if resolved:
                found.add(resolved)
    for form in soup.find_all('form', action=True):
        action = (form.get('action', '') or '').strip()
        if action:
            resolved = _resolve_url(action, base_url, base_domain)
            if resolved:
                found.add(resolved)
    for iframe in soup.find_all('iframe', src=True):
        src = (iframe.get('src', '') or '').strip()
        if src:
            resolved = _resolve_url(src, base_url, base_domain)
            if resolved:
                found.add(resolved)
    return list(found)[:10]


async def _scan_subpage(client, url: str, depth: int = 0) -> Dict[str, Any]:
    try:
        r = await client.get(url, timeout=8)
        if r.status_code != 200:
            return {'gateways': [], 'count': 0, 'evidence': []}
        html = r.text
        sub_soup = BeautifulSoup(html, 'html.parser')
        result = _detect_payment_gateways(sub_soup, html)
        if result['count'] > 0:
            return result
        if depth < 2:
            deeper_links = _find_payment_links(sub_soup, url)
            if deeper_links:
                tasks = [_scan_subpage(client, u, depth + 1) for u in deeper_links[:4]]
                deep_results = await asyncio.gather(*tasks, return_exceptions=True)
                all_gw = set()
                all_ev = []
                for dr in deep_results:
                    if isinstance(dr, dict) and dr.get('count', 0) > 0:
                        for gw in dr['gateways']:
                            if gw not in all_gw:
                                all_gw.add(gw)
                                all_ev.append(f"Subpage: {gw}")
                if all_gw:
                    return {'gateways': sorted(list(all_gw)), 'count': len(all_gw), 'evidence': all_ev}
    except Exception:
        pass
    return {'gateways': [], 'count': 0, 'evidence': []}


async def analyze_site(url: str) -> Dict[str, Any]:
    start = time.time()
    valid, normalized, error = validate_url(url)
    if not valid:
        return {'error': error}

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(REQUEST_TIMEOUT),
            follow_redirects=True,
            verify=True,
            headers={'User-Agent': USER_AGENT},
        ) as client:
            r = await client.get(normalized)
            html = r.text
            soup = BeautifulSoup(html, 'html.parser')

            cloudflare = _detect_cloudflare(r)
            captcha = _detect_captcha(soup, html)
            graphql_html = _detect_graphql(soup, html)
            cms = _detect_cms(soup, html)
            payments = _detect_payment_gateways(soup, html)
            checkout = _detect_checkout(soup, html)
            security = _analyze_security_headers(r)
            waf = _detect_waf(r)

            if payments['count'] == 0:
                parsed = urlparse(normalized)
                base = f"{parsed.scheme}://{parsed.netloc}"
                page_links = _find_payment_links(soup, normalized)
                subpage_urls = set(page_links)
                for path in PAYMENT_SUBPAGES:
                    subpage_urls.add(base + path)
                subpage_urls.discard(normalized.rstrip('/'))
                subpage_urls.discard(normalized)

                scan_tasks = [_scan_subpage(client, u) for u in list(subpage_urls)[:12]]
                sub_results = await asyncio.gather(*scan_tasks, return_exceptions=True)

                all_gateways = set(payments.get('gateways', []))
                all_evidence = list(payments.get('evidence', []))
                for res in sub_results:
                    if isinstance(res, dict) and res.get('count', 0) > 0:
                        for gw in res['gateways']:
                            if gw not in all_gateways:
                                all_gateways.add(gw)
                                all_evidence.append(f"Subpage: {gw}")
                payments = {
                    'gateways': sorted(list(all_gateways)),
                    'count': len(all_gateways),
                    'evidence': all_evidence,
                }

                if not checkout.get('features'):
                    for res in sub_results:
                        if isinstance(res, dict) and res.get('count', 0) > 0:
                            checkout = {'features': {'checkout': True}, 'score': 40}
                            break

            graphql_probe = await _probe_graphql(client, normalized)
            graphql = {
                'detected': graphql_html['detected'] or graphql_probe['detected'],
                'endpoints': graphql_probe.get('endpoints', []),
            }

        ssl_info = _analyze_ssl(normalized)
        elapsed = round(time.time() - start, 2)

        return {
            'url': normalized,
            'status_code': r.status_code,
            'cloudflare': cloudflare,
            'captcha': captcha,
            'graphql': graphql,
            'cms': cms,
            'payments': payments,
            'checkout': checkout,
            'security': security,
            'ssl': ssl_info,
            'waf': waf,
            'elapsed': elapsed,
        }
    except httpx.TimeoutException:
        return {'error': 'Request timeout - website took too long to respond'}
    except httpx.ConnectError:
        return {'error': 'Connection error - unable to reach website'}
    except Exception as e:
        return {'error': f'Analysis failed: {str(e)[:80]}'}


def _esc(text: str) -> str:
    if not text or text == "Unknown":
        return text
    for ch in ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']:
        text = text.replace(ch, '')
    if len(text) > 50:
        text = text[:47] + "..."
    return text


def format_result(data: Dict[str, Any], username: str = "") -> str:
    if 'error' in data:
        return (
            f"**Analysis Failed**\n\n"
            f"Error: {data['error']}\n\n"
            f"Check the URL and try again."
        )

    url = data.get('url', '?')
    elapsed = data.get('elapsed', 0)

    payments = data.get('payments', {})
    gw_list = payments.get('gateways', [])
    gw_text = ", ".join(gw_list) if gw_list else "None Detected"

    captcha = data.get('captcha', {})
    cap_text = ", ".join(captcha.get('types', [])) if captcha.get('detected') else "Not Protected"

    cf = data.get('cloudflare', {})
    cf_text = "Protected" if cf.get('detected') else "Not Protected"

    checkout = data.get('checkout', {})
    co_features = checkout.get('features', {})
    co_score = checkout.get('score', 0)
    if co_features.get('donation_form'):
        co_text = "Donation Form"
    elif co_score > 60:
        co_text = "Available"
    elif co_score > 30:
        co_text = "Partial"
    else:
        co_text = "Not Available"

    graphql = data.get('graphql', {})
    gql_text = "Available" if graphql.get('detected') else "Not Found"

    ssl_info = data.get('ssl', {})
    ssl_valid = "Valid" if ssl_info.get('valid') else "Invalid"
    ssl_issuer = _esc(ssl_info.get('issuer', 'Unknown'))
    ssl_subject = _esc(ssl_info.get('subject', 'Unknown'))
    ssl_expires = _esc(ssl_info.get('expires', 'Unknown'))

    security = data.get('security', {})
    sec_score = security.get('score', 0)

    cms = data.get('cms', {})
    cms_text = cms.get('detected', 'Unknown')

    waf = data.get('waf', {})
    waf_list = waf.get('detected', [])
    waf_text = ", ".join(waf_list) if waf_list else "None"

    CARD_ACCEPTING = {
        'stripe', 'braintree', 'square', 'authorize.net', 'adyen', 'worldpay',
        'sagepay', 'razorpay', 'cybersource', 'elavon', 'heartland', 'bluepay',
        'firstdata', 'chase paymentech', 'fiserv', 'ingenico', 'recurly',
        'spreedly', 'payflow', 'clover', 'paystack', 'moneris', 'usaepay',
        'paysafe', 'eway', 'airwallex', 'viva wallet', 'bambora', 'paysimple',
        'paytrace', 'securepay', 'merchant one', 'payeezy', 'payway',
        'woocommerce payments', 'shopify payments', 'quickbooks payments',
        'cognito forms', 'donorbox', 'paypal', 'venmo', 'helcim', 'cardconnect',
        'flywire', 'cashnet', 'touchnet', 'windcave', 'checkout.com', 'dlocal',
        'rapyd', 'formstack', 'jotform', 'gravity forms', 'wpforms',
        'blackbaud', 'iats payments', 'network for good', 'classy',
        'neoncrm', 'kindful', 'qgiv', 'givewp', 'give (wp)',
        '2checkout', 'mollie', 'wepay', 'payu',
    }
    card_systems = [gw for gw in gw_list if gw.lower() in CARD_ACCEPTING]
    cards_text = ", ".join(card_systems) if card_systems else "None Detected"

    checked_by = f"@{username}" if username else "Anonymous"

    sep = "\u2500" * 26

    msg = (
        f"\u250f\u2501\u2501\u2501\u2501\u300e Gateway Results \u300f\u2501\u2501\u2501\u2501\n\n"
        f"\U0001f50d **Domain:** {url}\n"
        f"\U0001f4b3 **Gateways:** {gw_text}\n"
        f"\U0001f512 **CAPTCHA:** {cap_text}\n"
        f"\U0001f6e1 **Cloudflare:** {cf_text}\n"
        f"\U0001f6d2 **Checkout:** {co_text}\n\n"
        f"\U0001f6e1 **Security:**\n"
        f"\u251c\u2500 Captcha: {'Detected' if captcha.get('detected') else 'Not Found'}\n"
        f"\u251c\u2500 Cloudflare: {cf_text}\n"
        f"\u251c\u2500 GraphQL: {gql_text}\n"
        f"\u2514\u2500 WAF: {waf_text}\n\n"
        f"\U0001f510 **SSL Details:**\n"
        f"\u251c\u2500 Status: {ssl_valid}\n"
        f"\u251c\u2500 Issuer: {ssl_issuer}\n"
        f"\u251c\u2500 Subject: {ssl_subject}\n"
        f"\u2514\u2500 Expires: {ssl_expires}\n\n"
        f"\U0001f6cd **Platform:**\n"
        f"\u251c\u2500 CMS: {cms_text}\n"
        f"\u251c\u2500 Cards: {cards_text}\n"
        f"\u2514\u2500 Headers Score: {sec_score}%\n\n"
        f"\u23f1 **Time:** {elapsed}s\n"
        f"\U0001f464 **Checked by:** {checked_by}\n\n"
        f"\u2517\u2501\u2501\u2501\u2501\u300e OGM Checker \u300f\u2501\u2501\u2501\u2501"
    )
    return msg
