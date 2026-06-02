import sys
import json
import os

GLOBAL_FILE = os.path.join(os.path.dirname(__file__), "skool_accounts.json")
USER_FILE = os.path.join(os.path.dirname(__file__), "user_skool_accounts.json")
STATUS_FILE = os.path.join(os.path.dirname(__file__), "skool_status.json")

def load_json(path, default=None):
    try:
        if os.path.exists(path):
            with open(path, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return default if default is not None else {}

def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)

def get_status():
    return load_json(STATUS_FILE, {})

def get_accounts(user_id, is_admin=False):
    status = get_status()
    accounts = []

    if is_admin:
        global_accs = load_json(GLOBAL_FILE, [])
        for acc in global_accs:
            email = acc.get("email", "")
            accounts.append({
                "email": email,
                "password": acc.get("password", ""),
                "type": "global",
                "status": status.get(email, "unknown"),
            })

    user_data = load_json(USER_FILE, {})
    user_accs = user_data.get(str(user_id), [])
    for acc in user_accs:
        email = acc.get("email", "")
        accounts.append({
            "email": email,
            "password": acc.get("password", ""),
            "type": "user",
            "status": status.get(email, "unknown"),
        })

    return accounts

def add_account(user_id, email, password, is_admin=False):
    if is_admin:
        data = load_json(GLOBAL_FILE, [])
        for acc in data:
            if acc["email"].lower() == email.lower():
                return {"error": "Account already exists"}
        data.append({"email": email, "password": password})
        save_json(GLOBAL_FILE, data)
        status = get_status()
        if email in status:
            del status[email]
            save_json(STATUS_FILE, status)
        return {"added": True, "type": "global"}
    else:
        data = load_json(USER_FILE, {})
        uid = str(user_id)
        if uid not in data:
            data[uid] = []
        for acc in data[uid]:
            if acc["email"].lower() == email.lower():
                return {"error": "Account already exists"}
        data[uid].append({"email": email, "password": password})
        save_json(USER_FILE, data)
        status = get_status()
        if email in status:
            del status[email]
            save_json(STATUS_FILE, status)
        return {"added": True, "type": "user"}

def remove_account(user_id, email, is_admin=False):
    if is_admin:
        data = load_json(GLOBAL_FILE, [])
        new_data = [a for a in data if a["email"].lower() != email.lower()]
        if len(new_data) < len(data):
            save_json(GLOBAL_FILE, new_data)
            return {"removed": True, "type": "global"}

    data = load_json(USER_FILE, {})
    uid = str(user_id)
    if uid in data:
        new_list = [a for a in data[uid] if a["email"].lower() != email.lower()]
        if len(new_list) < len(data[uid]):
            data[uid] = new_list
            if not data[uid]:
                del data[uid]
            save_json(USER_FILE, data)
            return {"removed": True, "type": "user"}

    return {"removed": False}

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(json.dumps({"error": "Usage: web_skool_accounts.py <action> <user_id> [is_admin] [args...]"}))
        sys.exit(1)

    action = sys.argv[1]
    user_id = sys.argv[2]
    is_admin = sys.argv[3] == "true" if len(sys.argv) > 3 else False

    if action == "list":
        accounts = get_accounts(user_id, is_admin)
        print(json.dumps({"accounts": accounts, "count": len(accounts)}))
    elif action == "add":
        email = sys.argv[4] if len(sys.argv) > 4 else ""
        password = sys.argv[5] if len(sys.argv) > 5 else ""
        if not email or not password:
            print(json.dumps({"error": "Email and password required"}))
        else:
            result = add_account(user_id, email, password, is_admin)
            print(json.dumps(result))
    elif action == "remove":
        email = sys.argv[4] if len(sys.argv) > 4 else ""
        result = remove_account(user_id, email, is_admin)
        print(json.dumps(result))
    else:
        print(json.dumps({"error": f"Unknown action: {action}"}))
